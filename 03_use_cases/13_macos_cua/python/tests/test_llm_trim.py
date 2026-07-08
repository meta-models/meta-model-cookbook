from metacua.llm import retain_most_recent_images

MARKER = "[Screenshot has been truncated to save context]"


def msg(i):
    return {
        "role": "user",
        "content": [
            {"type": "input_text", "text": "shot %d" % i},
            {"type": "input_image", "image_url": "data:image/png;base64,%d" % i},
        ],
    }


def image_types(conversation):
    return [m["content"][1]["type"] for m in conversation]


def test_retain_most_recent_images_does_not_prune_at_limit():
    conversation = [msg(i) for i in range(3)]
    trimmed = retain_most_recent_images(conversation, max_images=3)
    assert image_types(trimmed) == ["input_image"] * 3
    assert trimmed == conversation
    assert trimmed is not conversation


def test_retain_most_recent_images_prunes_to_max_without_mutating():
    conversation = [msg(i) for i in range(6)]
    trimmed = retain_most_recent_images(conversation, max_images=3)
    assert conversation[0]["content"][1]["type"] == "input_image"
    assert image_types(trimmed) == [
        "input_text",
        "input_text",
        "input_text",
        "input_image",
        "input_image",
        "input_image",
    ]
    assert trimmed[0]["content"][1] == {"type": "input_text", "text": MARKER}


def test_retain_most_recent_images_recursive_detector_and_non_mutation():
    nested = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "outer"},
                {
                    "type": "container",
                    "child": {"image_url": "data:image/png;base64,old"},
                },
            ],
        },
        msg(1),
        msg(2),
    ]
    trimmed = retain_most_recent_images(nested, max_images=1)
    assert nested[0]["content"][1]["child"]["image_url"] == "data:image/png;base64,old"
    assert trimmed[0]["content"][1]["child"] == {
        "type": "input_text",
        "text": MARKER,
    }
    assert trimmed[1]["content"][1]["type"] == "input_text"
    assert trimmed[2]["content"][1]["type"] == "input_image"


def test_retain_most_recent_images_max_images_floor():
    conversation = [msg(i) for i in range(3)]
    trimmed = retain_most_recent_images(conversation, max_images=0)
    assert image_types(trimmed) == ["input_text", "input_text", "input_image"]
    assert trimmed[0]["content"][1]["text"] == MARKER
