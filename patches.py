import ssl


def apply_ssl_patch():
    """
    Intercepts the faulty SSL call in the mattermostdriver library and forces
    SERVER_AUTH purpose for Python 3.10+. This is a workaround for a known
    bug in the library's SSL context creation.
    """
    orig_create_default_context = ssl.create_default_context

    def patched_create_default_context(*args, **kwargs):
        kwargs["purpose"] = ssl.Purpose.SERVER_AUTH
        return orig_create_default_context(*args, **kwargs)

    ssl.create_default_context = patched_create_default_context
    print("Applied SSL patch for mattermostdriver.")
