using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;

namespace SpecGuard.Scanner.Tests;

public class ScanApiTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private const string Controller = """
        [ApiController, Route("api/[controller]")]
        public class PetsController : ControllerBase
        {
            /// <summary>All pets.</summary>
            [HttpGet] public IActionResult List() => Ok();
        }
        """;

    [Fact]
    public async Task Health_returns_ok()
    {
        var body = await factory.CreateClient().GetFromJsonAsync<JsonElement>("/health");
        Assert.Equal("ok", body.GetProperty("status").GetString());
    }

    [Fact]
    public async Task Scan_returns_routes_in_camel_case()
    {
        var response = await factory.CreateClient().PostAsJsonAsync("/scan", new
        {
            files = new Dictionary<string, string> { ["Pets.cs"] = Controller, ["notes.txt"] = "ignored" },
        });

        response.EnsureSuccessStatusCode();
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal(1, body.GetProperty("filesScanned").GetInt32());
        var route = Assert.Single(body.GetProperty("routes").EnumerateArray());
        Assert.Equal("get", route.GetProperty("method").GetString());
        Assert.Equal("/api/pets", route.GetProperty("path").GetString());
        Assert.Equal("Pets.cs", route.GetProperty("file").GetString());
        Assert.Equal("All pets.", route.GetProperty("doc").GetString());
    }

    [Fact]
    public async Task Scan_without_files_is_a_validation_problem()
    {
        var response = await factory.CreateClient().PostAsJsonAsync("/scan", new { files = new Dictionary<string, string>() });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
    }

    [Fact]
    public async Task Scan_over_configured_limit_returns_413()
    {
        var client = factory
            .WithWebHostBuilder(b => b.ConfigureAppConfiguration((_, config) =>
                config.AddInMemoryCollection(new Dictionary<string, string?> { ["Scanner:MaxTotalChars"] = "10" })))
            .CreateClient();

        var response = await client.PostAsJsonAsync("/scan", new { files = new Dictionary<string, string> { ["Pets.cs"] = Controller } });
        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, response.StatusCode);
    }

    [Fact]
    public async Task OpenApi_document_describes_scan_endpoint()
    {
        var doc = await factory.CreateClient().GetFromJsonAsync<JsonElement>("/openapi/v1.json");
        Assert.True(doc.GetProperty("paths").TryGetProperty("/scan", out _));
    }
}
