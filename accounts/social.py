def verify_token(provider, id_token):
    """Seam. Real provider verification drops in later; tests monkeypatch this."""
    raise NotImplementedError("social token verification is not wired in this slice")
