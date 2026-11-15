from maxxing import voice


def test_text_language():
    assert voice.text_language("Can we speak English from now on?") == "en"
    assert voice.text_language("Est-ce que tu peux regarder si mon site marche ?") == "fr"
    assert voice.text_language("Ok") is None
