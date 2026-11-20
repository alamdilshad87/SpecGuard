from app.core.codescan import compare_with_spec, normalize_path, scan_js, scan_python, scan_sources, shape
from app.core.parser import parse_spec
from tests.conftest import EXAMPLES

FLASK_APP = '''
from flask import Blueprint, Flask
app = Flask(__name__)
bp = Blueprint("users", __name__, url_prefix="/users")

@bp.route("/<int:user_id>", methods=["GET", "DELETE"])
def user(user_id):
    """Fetch or delete one user."""

@app.route("/ping")
def ping():
    pass
'''

FASTAPI_ROUTER = '''
from fastapi import APIRouter
router = APIRouter(prefix="/orders")

@router.post("/")
async def create_order():
    """Create an order."""
'''

EXPRESS_APP = """
const router = express.Router();
router.get('/carts/:cartId', handler);
router.post("/carts", handler);
axios.get('/not-a-route');
"""


def test_normalize_path_and_shape():
    assert normalize_path("<int:id>") == "/{id}"
    assert normalize_path("/a/:id/") == "/a/{id}"
    assert shape("get", "/books/{book_id}") == shape("GET", "/books/{bookId}") == "GET /books/{}"


def test_scan_flask_and_fastapi():
    flask = {r.key for r in scan_python(FLASK_APP, "app.py")}
    assert flask == {"GET /users/{user_id}", "DELETE /users/{user_id}", "GET /ping"}

    (order,) = scan_python(FASTAPI_ROUTER, "orders.py")
    assert order.key == "POST /orders"
    assert order.doc == "Create an order."


def test_scan_express_skips_http_clients():
    assert {r.key for r in scan_js(EXPRESS_APP, "routes.js")} == {"GET /carts/{cartId}", "POST /carts"}


def test_scan_sources_ignores_unsupported_and_vendored_files():
    files = {
        "app.py": FLASK_APP,
        "node_modules/lib/index.js": EXPRESS_APP,
        "README.md": "@app.get('/nope')",
        "broken.py": "def (:",
    }
    assert {r.file for r in scan_sources(files)} == {"app.py"}


def test_demo_server_matches_v1_and_drifts_from_v2(spec_v1, spec_v2):
    routes = scan_sources({"mock_bookstore.py": (EXAMPLES / "mock_bookstore.py").read_text()})

    v1 = compare_with_spec(routes, parse_spec(spec_v1))
    assert v1["in_sync"] is True
    assert v1["summary"]["matched"] == 4

    v2 = compare_with_spec(routes, parse_spec(spec_v2))
    assert v2["in_sync"] is False
    assert [r["key"] for r in v2["undocumented_in_spec"]] == ["DELETE /books/{book_id}"]
    assert [o["operation"] for o in v2["not_implemented_in_code"]] == ["GET /authors"]
