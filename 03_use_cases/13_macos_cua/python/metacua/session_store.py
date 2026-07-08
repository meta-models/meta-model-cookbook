"""Record and inspect LLM sessions under the ~/.metacua app state."""

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .args import Args
from .config import metacua_home_url
from .errors import CLIError
from .llm import LLMResult, LLMToolCall

_ALLOWED_TRACE_ID_EXTRA = set("-_")


def _image_extension(prefix: str) -> str:
    """Map a ``data:image/<subtype>;base64`` prefix to a file extension."""
    subtype = ""
    marker = "image/"
    start = prefix.find(marker)
    if start != -1:
        rest = prefix[start + len(marker):]
        for stop in (";", ",", "+"):
            idx = rest.find(stop)
            if idx != -1:
                rest = rest[:idx]
        subtype = rest.strip().lower()
    if subtype in ("jpeg", "jpg"):
        return ".jpg"
    if subtype and subtype.isalnum():
        return f".{subtype}"
    return ".png"


class _TraceImageWriter:
    """Extracts inline base64 images into sidecar files next to the trace.

    Screenshots are written once per unique content hash under
    ``<traces>/<trace_id>/`` so the JSONL keeps one small reference per image
    instead of a multi-hundred-KB data URI. Deduping by hash means a screenshot
    that reappears across turns/records is stored a single time.
    """

    def __init__(self, image_dir: Path, rel_prefix: str) -> None:
        self._image_dir = image_dir
        self._rel_prefix = rel_prefix
        self._by_hash: Dict[str, str] = {}
        self._created_dir = False
        self.saved_count = 0

    def save(self, prefix: str, encoded: str) -> Optional[str]:
        """Write the image and return a reference string, or None to redact."""
        try:
            raw = base64.b64decode(encoded, validate=False)
        except (ValueError, TypeError):
            return None
        if not raw:
            return None
        digest = hashlib.sha1(raw).hexdigest()[:16]
        relpath = self._by_hash.get(digest)
        if relpath is None:
            name = f"{digest}{_image_extension(prefix)}"
            self._write_file(name, raw)
            relpath = f"{self._rel_prefix}/{name}"
            self._by_hash[digest] = relpath
            self.saved_count += 1
        return f"{prefix},<saved {relpath} ({len(raw)} bytes)>"

    def _write_file(self, name: str, raw: bytes) -> None:
        if not self._created_dir:
            self._image_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self._image_dir, 0o700)
            self._created_dir = True
        path = self._image_dir / name
        if path.exists():
            return
        tmp = self._image_dir / f"{name}.tmp"
        with open(tmp, "wb") as handle:
            handle.write(raw)
        os.chmod(tmp, 0o600)
        tmp.replace(path)


@dataclass
class StoredLLMCallRef:
    record_id: str
    display_id: str
    trace_id: str
    storage_path: str


class SessionStore:
    shared: "SessionStore"

    @property
    def storage_url(self) -> Path:
        return metacua_home_url() / "traces"

    @property
    def _legacy_trace_storage_url(self) -> Path:
        return Path.home() / ".local" / "share" / "metacua" / "traces"

    @property
    def _legacy_global_storage_url(self) -> Path:
        return Path.home() / ".local" / "share" / "metacua" / "llm-sessions.jsonl"

    def append_llm_call(
        self,
        config,
        backend_label: str,
        goal_id: str,
        goal: str,
        step: int,
        request_conversation: List[Dict[str, Any]],
        result: LLMResult,
    ) -> StoredLLMCallRef:
        record_id = str(uuid.uuid4())
        trace_id = self._safe_trace_id(goal_id)
        trace_url = self.trace_file_url(trace_id)
        message_history = list(request_conversation) + list(result.assistant_items)
        image_writer = _TraceImageWriter(
            image_dir=self.storage_url / trace_id,
            rel_prefix=trace_id,
        )
        record: Dict[str, Any] = {
            "record_id": record_id,
            "timestamp": self._iso_timestamp(),
            "trace_id": trace_id,
            "trace_file": str(trace_url),
            "backend": backend_label,
            "model": config.model,
            "base_url": config.base_url,
            "goal_id": goal_id,
            "goal": goal,
            "step": step,
            "response_id": result.response_id,
            "session_ids": result.session_ids,
            "finish": result.finish,
            "text": result.text,
            "thinking": result.thinking,
            "tool_calls": [self._tool_call_object(call, image_writer) for call in result.tool_calls],
            "request": {"conversation": self._sanitized_json(request_conversation, image_writer)},
            "response": self._sanitized_json(result.raw_response, image_writer),
            "message_history": self._sanitized_json(message_history, image_writer),
        }
        if image_writer.saved_count:
            record["images"] = {
                "dir": str(self.storage_url / trace_id),
                "count": image_writer.saved_count,
            }

        self._append(record, trace_url)
        display_id = (
            (result.session_ids[0] if result.session_ids else None)
            or result.response_id
            or record_id
        )
        return StoredLLMCallRef(
            record_id=record_id,
            display_id=display_id,
            trace_id=trace_id,
            storage_path=str(trace_url),
        )

    def load_recent(self, limit: int) -> List[Dict[str, Any]]:
        all_records = self._load_all()
        count = max(0, limit)
        if count == 0:
            return []
        return list(reversed(all_records[-count:]))

    def load_matching(self, id: str) -> Optional[Dict[str, Any]]:
        needle = id.strip()
        if not needle:
            return None
        for record in reversed(self._load_all()):
            if self._record_matches(record, needle):
                return record
        return None

    def trace_file_url(self, trace_id: str) -> Path:
        return self.storage_url / f"{self._safe_trace_id(trace_id)}.jsonl"

    def _append(self, record: Dict[str, Any], url: Path) -> None:
        try:
            url.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(url.parent, 0o700)
        except OSError:
            raise CLIError(f"failed to create session history at {url}")
        try:
            if not url.exists():
                url.touch()
                os.chmod(url, 0o600)
            data = json.dumps(record, sort_keys=True)
            with open(url, "a", encoding="utf-8") as handle:
                handle.write(data)
                handle.write("\n")
        except OSError:
            raise CLIError(f"failed to open session history at {url}")

    def _load_all(self) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []

        if self._legacy_global_storage_url.exists():
            records.extend(self._load_records(self._legacy_global_storage_url))

        records.extend(self._load_trace_records(self._legacy_trace_storage_url))
        records.extend(self._load_trace_records(self.storage_url))

        records.sort(key=lambda r: self._string(r.get("timestamp")) or "")
        return records

    def _load_trace_records(self, directory: Path) -> List[Dict[str, Any]]:
        if not directory.exists():
            return []
        records: List[Dict[str, Any]] = []
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return []
        for url in entries:
            if url.suffix == ".jsonl":
                records.extend(self._load_records(url))
        return records

    def _load_records(self, url: Path) -> List[Dict[str, Any]]:
        try:
            text = url.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise CLIError("could not read session history as UTF-8")
        except OSError:
            return []
        records: List[Dict[str, Any]] = []
        for line in text.split("\n"):
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    @staticmethod
    def _tool_call_object(
        call: LLMToolCall, image_writer: Optional["_TraceImageWriter"] = None
    ) -> Dict[str, Any]:
        return {
            "id": call.id,
            "name": call.name,
            "input": SessionStore._sanitized_json(call.input, image_writer),
        }

    @staticmethod
    def _sanitized_json(value: Any, image_writer: Optional["_TraceImageWriter"] = None) -> Any:
        if isinstance(value, dict):
            return {
                key: SessionStore._sanitized_json(child, image_writer)
                for key, child in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [SessionStore._sanitized_json(child, image_writer) for child in value]
        if isinstance(value, str):
            return SessionStore._sanitized_string(value, image_writer)
        if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
            return value
        return str(value)

    @staticmethod
    def _sanitized_string(
        value: str, image_writer: Optional["_TraceImageWriter"] = None
    ) -> str:
        if not value.startswith("data:image/"):
            return value
        comma = value.find(",")
        if comma == -1:
            return "data:image/<redacted>"
        prefix = value[:comma]
        encoded = value[comma + 1:]
        if image_writer is not None:
            reference = image_writer.save(prefix, encoded)
            if reference is not None:
                return reference
        return f"{prefix},<redacted {len(encoded.encode('utf-8'))} base64 bytes>"

    @staticmethod
    def _record_matches(record: Dict[str, Any], id: str) -> bool:
        if SessionStore._string(record.get("record_id")) == id:
            return True
        if SessionStore._string(record.get("response_id")) == id:
            return True
        if SessionStore._string(record.get("trace_id")) == id:
            return True
        if SessionStore._string(record.get("goal_id")) == id:
            return True
        trace_file = SessionStore._string(record.get("trace_file"))
        if trace_file is not None:
            name = os.path.basename(trace_file)
            if name == id:
                return True
            if os.path.splitext(name)[0] == id:
                return True
        session_ids = record.get("session_ids")
        if isinstance(session_ids, list) and id in session_ids:
            return True
        return False

    @staticmethod
    def _safe_trace_id(raw: str) -> str:
        trimmed = raw.strip()
        source = trimmed if trimmed else str(uuid.uuid4())
        chars = [
            ch if (ch.isalnum() and ch.isascii()) or ch in _ALLOWED_TRACE_ID_EXTRA else "-"
            for ch in source
        ]
        safe = "".join(chars).strip("-")
        return safe if safe else str(uuid.uuid4())

    @staticmethod
    def _string(value: Any) -> Optional[str]:
        if value is None:
            return None
        return value if isinstance(value, str) else None

    @staticmethod
    def _iso_timestamp() -> str:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


SessionStore.shared = SessionStore()


def run_sessions(raw: List[str]) -> None:
    args = Args(raw)
    store = SessionStore.shared
    if args.flag("path"):
        print(str(store.storage_url))
        return

    id = args.string("id") or args.string("session-id") or args.string("response-id")
    as_json = args.flag("json")
    history = args.flag("history")

    if id:
        record = store.load_matching(id)
        if record is None:
            raise CLIError(f"no stored LLM session matched '{id}'", code=2)
        if history:
            print_pretty_json(record.get("message_history") or [])
        elif as_json:
            print_pretty_json(record)
        else:
            for line in session_detail_lines(record, str(store.storage_url)):
                print(line)
        return

    if history:
        raise CLIError("--history requires --id", code=2)

    limit = args.int("limit")
    limit = 20 if limit is None else limit
    records = store.load_recent(limit)
    if as_json:
        print_pretty_json(records)
    else:
        for line in session_summary_lines(records, str(store.storage_url)):
            print(line)


def session_summary_lines(records: List[Dict[str, Any]], storage_path: str) -> List[str]:
    if not records:
        return [f"No stored LLM sessions at {storage_path}"]

    lines = [f"Stored LLM sessions at {storage_path}"]
    for record in records:
        timestamp = _string_field(record, "timestamp") or "unknown-time"
        model = _string_field(record, "model") or "unknown-model"
        finish = _string_field(record, "finish") or "unknown"
        step_val = _int_field(record, "step")
        step = str(step_val) if step_val is not None else "?"
        trace = _string_field(record, "trace_id") or _string_field(record, "goal_id") or "-"
        session = _primary_session_id(record) or "-"
        response = _string_field(record, "response_id") or "-"
        goal = _excerpt(_string_field(record, "goal") or "", 54)
        text = _excerpt(_string_field(record, "text") or "", 72)
        lines.append(
            f"{timestamp} trace={trace} step={step} finish={finish} model={model} "
            f"session={session} response={response}"
        )
        if goal:
            lines.append(f"  goal: {goal}")
        if text:
            lines.append(f"  text: {text}")
    return lines


def session_detail_lines(record: Dict[str, Any], storage_path: str) -> List[str]:
    lines: List[str] = []
    lines.append("LLM session")
    lines.append(f"  record_id   {_string_field(record, 'record_id') or '-'}")
    lines.append(f"  timestamp   {_string_field(record, 'timestamp') or '-'}")
    trace_id = _string_field(record, "trace_id") or _string_field(record, "goal_id") or "-"
    lines.append(f"  trace_id    {trace_id}")
    sessions = _session_ids(record)
    lines.append(f"  session_ids {', '.join(sessions) if sessions else '-'}")
    lines.append(f"  response_id {_string_field(record, 'response_id') or '-'}")
    lines.append(f"  backend     {_string_field(record, 'backend') or '-'}")
    lines.append(f"  model       {_string_field(record, 'model') or '-'}")
    step_val = _int_field(record, "step")
    lines.append(f"  step        {step_val if step_val is not None else '-'}")
    lines.append(f"  finish      {_string_field(record, 'finish') or '-'}")
    lines.append(f"  goal        {_string_field(record, 'goal') or ''}")
    text = _string_field(record, "text") or ""
    if text:
        lines.append(f"  text        {text}")
    tool_calls = record.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        lines.append("  tool_calls")
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = _string_field(call, "name") or "-"
            call_id = _string_field(call, "id") or "-"
            lines.append(f"    {name} id={call_id}")
    images = record.get("images")
    if isinstance(images, dict):
        count = _int_field(images, "count")
        image_dir = _string_field(images, "dir")
        if count is not None:
            lines.append(f"  images      {count} saved in {image_dir or '-'}")
    trace_file = _string_field(record, "trace_file")
    if trace_file:
        lines.append(f"  trace_file  {trace_file}")
    lines.append(f"  storage     {storage_path}")
    lines.append("Use `metacua sessions --id <id> --json` for the full sanitized record.")
    lines.append("Use `metacua sessions --id <id> --history` for sanitized message history only.")
    return lines


def print_pretty_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _primary_session_id(record: Dict[str, Any]) -> Optional[str]:
    ids = _session_ids(record)
    return ids[0] if ids else None


def _session_ids(record: Dict[str, Any]) -> List[str]:
    value = record.get("session_ids")
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _string_field(record: Dict[str, Any], key: str) -> Optional[str]:
    value = record.get(key)
    if value is None:
        return None
    return value if isinstance(value, str) else None


def _int_field(record: Dict[str, Any], key: str) -> Optional[int]:
    value = record.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _excerpt(value: str, max_length: int) -> str:
    one_line = value.replace("\n", " ").strip()
    if len(one_line) <= max_length:
        return one_line
    return one_line[: max(0, max_length - 3)] + "..."
