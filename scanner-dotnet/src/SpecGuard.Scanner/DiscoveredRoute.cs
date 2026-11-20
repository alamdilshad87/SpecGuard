namespace SpecGuard.Scanner;

/// <summary>An HTTP endpoint found in C# source code.</summary>
/// <param name="Method">Lower-case HTTP method, e.g. <c>get</c>.</param>
/// <param name="Path">OpenAPI-style path, e.g. <c>/api/books/{id}</c>.</param>
/// <param name="File">Path of the source file, as supplied by the caller.</param>
/// <param name="Line">1-based line of the action method or <c>Map*</c> call.</param>
/// <param name="Handler">Action method name, or <c>Controller.Action</c> for controllers.</param>
/// <param name="Doc">XML doc summary or <c>WithSummary</c>/<c>WithDescription</c> text, if any.</param>
public sealed record DiscoveredRoute(string Method, string Path, string File, int Line, string Handler, string Doc);

/// <summary>Result of scanning a set of source files.</summary>
public sealed record ScanResult(int FilesScanned, IReadOnlyList<DiscoveredRoute> Routes);
