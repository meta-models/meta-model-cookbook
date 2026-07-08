def test_pure_modules_import_without_pyobjc():
    import metacua.args  # noqa: F401
    import metacua.config  # noqa: F401
    import metacua.errors  # noqa: F401
    import metacua.computer_actions  # noqa: F401
    import metacua.key_names  # noqa: F401
    import metacua.letterbox  # noqa: F401
    import metacua.llm  # noqa: F401
    import metacua.osworld  # noqa: F401
    import metacua.session_store  # noqa: F401
    import metacua.slash_commands  # noqa: F401
    import metacua.system_prompt  # noqa: F401
    import metacua.terminal_state  # noqa: F401
