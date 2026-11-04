import os, tempfile
os.environ.setdefault("STEPPROOF_DATA", tempfile.mkdtemp(prefix="stepproof-test-"))
os.environ.setdefault("STEPPROOF_SIGNING_KEY", "dev-insecure-key-stepproof-v2-local")
