using SpecGuard.Scanner.Api;

var builder = WebApplication.CreateBuilder(args);

builder.Services.Configure<ScannerLimits>(builder.Configuration.GetSection(ScannerLimits.Section));
builder.Services.AddProblemDetails();
builder.Services.AddOpenApi();

// Requests carry source code as JSON; allow some headroom over the character limit.
builder.WebHost.ConfigureKestrel(kestrel => kestrel.Limits.MaxRequestBodySize = 32 * 1024 * 1024);

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();
app.MapOpenApi();
app.MapScanEndpoints();

app.Run();

/// <summary>Exposed so integration tests can host the app with WebApplicationFactory.</summary>
public partial class Program;
