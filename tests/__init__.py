import os
import tempfile

# Tests write to a disposable artifact store, never to recorded evidence.
os.environ.setdefault("RIFT_ARTIFACTS", tempfile.mkdtemp(prefix="rift-test-artifacts-"))
