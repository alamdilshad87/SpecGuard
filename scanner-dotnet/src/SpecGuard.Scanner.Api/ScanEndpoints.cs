using Microsoft.Extensions.Options;

namespace SpecGuard.Scanner.Api;

/// <summary>Request body for <c>POST /scan</c>: source files keyed by path.</summary>
public sealed record ScanRequest(Dictionary<string, string>? Files);

/// <summary>Limits on a single scan request, bound from the <c>Scanner</c> config section.</summary>
public sealed class ScannerLimits
{
    public const string Section = "Scanner";

    public int MaxFiles { get; set; } = 2000;
    public int MaxTotalChars { get; set; } = 10 * 1024 * 1024;
}

public static class ScanEndpoints
{
    public static IEndpointRouteBuilder MapScanEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/health", () => Results.Ok(new { status = "ok" }))
            .WithName("Health")
            .WithSummary("Liveness probe");

        app.MapPost("/scan", Scan)
            .WithName("Scan")
            .WithSummary("Find ASP.NET Core routes in C# source files")
            .WithDescription("Files that are not .cs, or live under bin/ or obj/, are ignored.")
            .Produces<ScanResult>()
            .ProducesValidationProblem()
            .ProducesProblem(StatusCodes.Status413PayloadTooLarge);

        return app;
    }

    private static IResult Scan(ScanRequest request, IOptions<ScannerLimits> options, ILogger<ScanRequest> logger)
    {
        if (request.Files is null || request.Files.Count == 0)
            return Results.ValidationProblem(new Dictionary<string, string[]>
            {
                ["files"] = ["Provide at least one file as {\"path\": \"source\"}."],
            });

        var limits = options.Value;
        var totalChars = request.Files.Values.Sum(s => (long)(s?.Length ?? 0));
        if (request.Files.Count > limits.MaxFiles || totalChars > limits.MaxTotalChars)
            return Results.Problem(
                statusCode: StatusCodes.Status413PayloadTooLarge,
                title: "Scan request too large",
                detail: $"Limit is {limits.MaxFiles} files and {limits.MaxTotalChars} characters per request.");

        var files = request.Files.Where(f => f.Value is not null).ToDictionary(f => f.Key, f => f.Value);
        var result = RouteScanner.Scan(files);
        logger.LogInformation("Scanned {Files} C# files, found {Routes} routes", result.FilesScanned, result.Routes.Count);
        return Results.Ok(result);
    }
}
