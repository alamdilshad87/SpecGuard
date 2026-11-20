using System.Text.RegularExpressions;

namespace SpecGuard.Scanner;

/// <summary>Combines and normalizes ASP.NET Core route templates into OpenAPI-style paths.</summary>
public static partial class RouteTemplate
{
    // {id:int}, {id?}, {id=5}, {*path}, {**slug} -> {id} / {path} / {slug}
    [GeneratedRegex(@"\{\*{0,2}([A-Za-z_]\w*)[^}]*\}")]
    private static partial Regex ParameterPattern();

    [GeneratedRegex("/{2,}")]
    private static partial Regex RepeatedSlashes();

    /// <summary>
    /// Combine a controller-level template with an action-level one. Action templates that start
    /// with <c>/</c> or <c>~/</c> are absolute and ignore the controller prefix, as in ASP.NET Core.
    /// </summary>
    public static string Combine(string prefix, string template)
    {
        if (template.StartsWith("~/", StringComparison.Ordinal))
            return template[1..];
        if (template.StartsWith('/'))
            return template;
        if (template.Length == 0)
            return prefix;
        if (prefix.Length == 0)
            return template;
        return prefix.TrimEnd('/') + "/" + template;
    }

    /// <summary>
    /// Join a <c>MapGroup</c> prefix with a minimal API template. Unlike <see cref="Combine"/>, a
    /// leading <c>/</c> on the template is still relative to the group.
    /// </summary>
    public static string Join(string prefix, string template) =>
        prefix.Length == 0 ? template : prefix.TrimEnd('/') + "/" + template.TrimStart('/');

    /// <summary>
    /// Replace <c>[controller]</c> / <c>[action]</c> tokens (lower-cased, since ASP.NET routing is
    /// case-insensitive and specs conventionally use lower-case paths), strip parameter constraints,
    /// and tidy slashes.
    /// </summary>
    public static string Normalize(string template, string controller = "", string action = "")
    {
        var path = template
            .Replace("[controller]", controller.ToLowerInvariant(), StringComparison.OrdinalIgnoreCase)
            .Replace("[action]", action.ToLowerInvariant(), StringComparison.OrdinalIgnoreCase);
        path = ParameterPattern().Replace(path, "{$1}");
        path = RepeatedSlashes().Replace("/" + path, "/");
        return path.Length > 1 ? path.TrimEnd('/') : path;
    }
}
