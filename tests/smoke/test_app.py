def test_app_imports() -> None:
    import app

    assert callable(app.render_app)


