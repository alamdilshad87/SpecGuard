using SpecGuard.Scanner;

namespace SpecGuard.Scanner.Tests;

public class RouteScannerTests
{
    private static List<string> Keys(string source) =>
        RouteScanner.ScanSource(source, "Test.cs").Select(r => $"{r.Method.ToUpperInvariant()} {r.Path}").ToList();

    [Fact]
    public void Finds_attribute_routes_on_controllers()
    {
        const string source = """
            [ApiController]
            [Route("api/[controller]")]
            public class OrdersController : ControllerBase
            {
                [HttpGet] public IActionResult List() => Ok();
                [HttpGet("{id:guid}")] public IActionResult Get(Guid id) => Ok();
                [HttpPost] public Task<IActionResult> CreateAsync() => null!;
                [HttpPut("{id}"), HttpPatch("{id}")] public IActionResult Update(Guid id) => Ok();
                [HttpDelete("~/admin/orders/{id}")] public IActionResult Purge(Guid id) => Ok();
                [Route("[action]")] [HttpGet] public IActionResult Search() => Ok();
                [AcceptVerbs("GET", "HEAD")] [Route("export")] public IActionResult Export() => Ok();

                public IActionResult NoAttributes() => Ok();
                private IActionResult Helper() => Ok();
                [NonAction] [HttpGet("hidden")] public IActionResult Hidden() => Ok();
            }
            """;

        Assert.Equal(
            [
                "GET /api/orders", "GET /api/orders/{id}", "POST /api/orders",
                "PUT /api/orders/{id}", "PATCH /api/orders/{id}", "DELETE /admin/orders/{id}",
                "GET /api/orders/search", "GET /api/orders/export", "HEAD /api/orders/export",
            ],
            Keys(source));
    }

    [Fact]
    public void Async_suffix_is_trimmed_from_action_token()
    {
        const string source = """
            [Route("[controller]/[action]")]
            public class ReportsController : Controller
            {
                [HttpGet] public Task<IActionResult> DailyAsync() => null!;
            }
            """;
        Assert.Equal(["GET /reports/daily"], Keys(source));
    }

    [Fact]
    public void Ignores_abstract_non_controller_and_conventionally_routed_classes()
    {
        const string source = """
            public abstract class BaseApiController : ControllerBase
            {
                [HttpGet("base")] public IActionResult Base() => Ok();
            }
            [NonController]
            public class FakeController { [HttpGet("fake")] public void Fake() { } }
            public class Service { [HttpGet("svc")] public void Run() { } }
            public class HomeController : Controller { [HttpGet] public IActionResult Index() => View(); }
            """;
        Assert.Empty(Keys(source));
    }

    [Fact]
    public void Reads_xml_doc_summary_and_handler_name()
    {
        const string source = """
            [ApiController, Route("users")]
            public class UsersController : ControllerBase
            {
                /// <summary>
                ///   Returns the <see cref="User"/> with the given id.
                /// </summary>
                [HttpGet("{id}")]
                public IActionResult Get(int id) => Ok();
            }
            """;
        var route = Assert.Single(RouteScanner.ScanSource(source, "Users.cs"));
        Assert.Equal("Returns the User with the given id.", route.Doc);
        Assert.Equal("UsersController.Get", route.Handler);
        Assert.Equal(8, route.Line);
    }

    [Fact]
    public void Finds_minimal_api_routes_with_groups_and_summaries()
    {
        const string source = """
            var app = WebApplication.Create(args);
            app.MapGet("/health", () => "ok").WithSummary("Liveness probe");

            var api = app.MapGroup("/api").WithTags("api");
            var carts = api.MapGroup("carts");
            carts.MapGet("/{cartId:int}", GetCart);
            carts.MapPost("/", (Cart c) => Results.Created());
            app.MapGroup("/v2").MapDelete("/carts/{id}", Handlers.Remove);
            app.MapGet(Constants.DynamicRoute, () => "skipped: not a literal");

            /// <summary>Fetch a cart with its items.</summary>
            static IResult GetCart(int cartId) => Results.Ok();
            """;

        var routes = RouteScanner.ScanSource(source, "Program.cs").ToList();
        Assert.Equal(
            ["GET /health", "GET /api/carts/{cartId}", "POST /api/carts", "DELETE /v2/carts/{id}"],
            routes.Select(r => $"{r.Method.ToUpperInvariant()} {r.Path}"));
        Assert.Equal("Liveness probe", routes[0].Doc);
        Assert.Equal(("GetCart", "Fetch a cart with its items."), (routes[1].Handler, routes[1].Doc));
        Assert.Equal("Remove", routes[3].Handler);
    }

    [Fact]
    public void Scan_skips_non_cs_and_build_output_and_tolerates_broken_code()
    {
        var result = RouteScanner.Scan(new Dictionary<string, string>
        {
            ["src/Broken.cs"] = "public class XController : ControllerBase { [HttpGet(\"x\")] public void X( {",
            ["src/obj/Generated.cs"] = "app.MapGet(\"/generated\", () => 1);",
            ["README.md"] = "app.MapGet(\"/docs\", () => 1);",
        });
        Assert.Equal(1, result.FilesScanned);
        Assert.Equal("/x", Assert.Single(result.Routes).Path);
    }

    [Fact]
    public void Example_bookstore_controller_matches_v1_spec()
    {
        var path = Path.Combine(RepoRoot(), "examples", "BookstoreApi", "BooksController.cs");
        var keys = Keys(File.ReadAllText(path));
        Assert.Equal(["GET /books", "POST /books", "GET /books/{bookId}", "DELETE /books/{bookId}"], keys);
    }

    private static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, "examples")))
            dir = dir.Parent;
        return dir?.FullName ?? throw new DirectoryNotFoundException("Could not find repository root");
    }
}
