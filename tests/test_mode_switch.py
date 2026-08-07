from app.ui.components.mode_switch import check_password


def test_no_password_allows():
    assert check_password("", None) is True
    assert check_password("anything", "") is True


def test_password_match():
    assert check_password("1234", "1234") is True


def test_password_mismatch():
    assert check_password("0000", "1234") is False
