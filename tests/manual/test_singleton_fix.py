"""Retired enterprise-WeChat notification check; no external requests are made."""

if __name__ == "__main__":
    print("SKIP: enterprise-WeChat notifications have been removed from LearnFlux.")
else:
    import pytest
    pytest.skip("Enterprise-WeChat notifications have been removed.", allow_module_level=True)
