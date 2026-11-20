using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace SpecGuard.Scanner;

/// <summary>
/// Finds ASP.NET Core endpoints in C# source using Roslyn syntax trees.
/// </summary>
/// <remarks>
/// Analysis is syntax-only: files are parsed but not compiled, so partial code, missing
/// references and compile errors are fine. The trade-off is that routes built from constants or
/// at runtime are not resolved; only string literals are.
/// </remarks>
public static partial class RouteScanner
{
    private static readonly Dictionary<string, string> HttpAttributes = new(StringComparer.Ordinal)
    {
        ["HttpGet"] = "get", ["HttpPost"] = "post", ["HttpPut"] = "put", ["HttpDelete"] = "delete",
        ["HttpPatch"] = "patch", ["HttpHead"] = "head", ["HttpOptions"] = "options",
    };

    private static readonly Dictionary<string, string> MapMethods = new(StringComparer.Ordinal)
    {
        ["MapGet"] = "get", ["MapPost"] = "post", ["MapPut"] = "put",
        ["MapDelete"] = "delete", ["MapPatch"] = "patch",
    };

    private static readonly string[] SkippedDirectories = ["bin", "obj", ".git", "node_modules"];

    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();

    /// <summary>Scan <c>{path: source}</c> pairs; non-<c>.cs</c> files and build output are ignored.</summary>
    public static ScanResult Scan(IReadOnlyDictionary<string, string> files)
    {
        var routes = new List<DiscoveredRoute>();
        var scanned = 0;
        foreach (var (file, source) in files.OrderBy(f => f.Key, StringComparer.Ordinal))
        {
            if (!IsScannable(file))
                continue;
            scanned++;
            routes.AddRange(ScanSource(source, file));
        }
        return new ScanResult(scanned, routes);
    }

    public static bool IsScannable(string file)
    {
        var parts = file.Replace('\\', '/').Split('/');
        return file.EndsWith(".cs", StringComparison.OrdinalIgnoreCase)
               && !parts.Any(p => SkippedDirectories.Contains(p, StringComparer.OrdinalIgnoreCase));
    }

    public static IEnumerable<DiscoveredRoute> ScanSource(string source, string file)
    {
        var root = CSharpSyntaxTree.ParseText(source).GetCompilationUnitRoot();
        return ScanControllers(root, file).Concat(ScanMinimalApis(root, file));
    }

    // ------------------------------------------------------------------ controllers

    private static IEnumerable<DiscoveredRoute> ScanControllers(CompilationUnitSyntax root, string file)
    {
        foreach (var cls in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
        {
            if (!IsController(cls))
                continue;

            var className = cls.Identifier.ValueText;
            var controller = className.EndsWith("Controller", StringComparison.Ordinal)
                ? className[..^"Controller".Length]
                : className;
            var classTemplates = Attributes(cls.AttributeLists, "Route").Select(FirstString).OfType<string>().ToList();
            if (classTemplates.Count == 0)
                classTemplates.Add("");

            foreach (var method in cls.Members.OfType<MethodDeclarationSyntax>())
            {
                if (!method.Modifiers.Any(SyntaxKind.PublicKeyword)
                    || method.Modifiers.Any(SyntaxKind.StaticKeyword)
                    || Attributes(method.AttributeLists, "NonAction").Any())
                    continue;

                var action = method.Identifier.ValueText;
                if (action.EndsWith("Async", StringComparison.Ordinal) && action.Length > "Async".Length)
                    action = action[..^"Async".Length]; // ASP.NET Core trims Async from action names

                var line = method.Identifier.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
                var doc = XmlSummary(method);

                foreach (var (verb, methodTemplate) in Endpoints(method))
                {
                    foreach (var classTemplate in classTemplates)
                    {
                        if (classTemplate.Length == 0 && methodTemplate.Length == 0)
                            continue; // conventional routing: path is not knowable from attributes
                        var path = RouteTemplate.Normalize(RouteTemplate.Combine(classTemplate, methodTemplate), controller, action);
                        yield return new DiscoveredRoute(verb, path, file, line, $"{className}.{method.Identifier.ValueText}", doc);
                    }
                }
            }
        }
    }

    private static bool IsController(ClassDeclarationSyntax cls)
    {
        if (cls.Modifiers.Any(SyntaxKind.AbstractKeyword) || Attributes(cls.AttributeLists, "NonController").Any())
            return false;
        if (Attributes(cls.AttributeLists, "ApiController").Any())
            return true;
        var bases = cls.BaseList?.Types.Select(t => SimpleName(t.Type.ToString())) ?? [];
        return bases.Any(b => b is "ControllerBase" or "Controller")
               || cls.Identifier.ValueText.EndsWith("Controller", StringComparison.Ordinal);
    }

    /// <summary>(verb, action template) pairs declared on an action method.</summary>
    private static IEnumerable<(string Verb, string Template)> Endpoints(MethodDeclarationSyntax method)
    {
        var routeTemplates = Attributes(method.AttributeLists, "Route").Select(FirstString).OfType<string>().ToList();
        var shared = routeTemplates.Count > 0 ? routeTemplates : [""];

        foreach (var attr in method.AttributeLists.SelectMany(l => l.Attributes))
        {
            var name = SimpleName(attr.Name.ToString());
            if (HttpAttributes.TryGetValue(name, out var verb))
            {
                // [HttpGet("x")] carries its own template; [HttpGet] uses the method's [Route]s.
                var own = FirstString(attr);
                foreach (var template in own is null ? shared : [own])
                    yield return (verb, template);
            }
            else if (name == "AcceptVerbs")
            {
                foreach (var v in PositionalStrings(attr))
                    foreach (var template in shared)
                        yield return (v.ToLowerInvariant(), template);
            }
        }
    }

    // ------------------------------------------------------------------ minimal APIs

    private static IEnumerable<DiscoveredRoute> ScanMinimalApis(CompilationUnitSyntax root, string file)
    {
        var groups = GroupPrefixes(root);
        // Handlers can be methods or, in top-level Program.cs files, local functions.
        var methodDocs = root.DescendantNodes()
            .Select(n => n switch
            {
                MethodDeclarationSyntax m => (Name: m.Identifier.ValueText, Node: (SyntaxNode)m),
                LocalFunctionStatementSyntax f => (Name: f.Identifier.ValueText, Node: f),
                _ => (Name: "", Node: n),
            })
            .Where(x => x.Name.Length > 0)
            .GroupBy(x => x.Name)
            .ToDictionary(g => g.Key, g => XmlSummary(g.First().Node));

        foreach (var call in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (call.Expression is not MemberAccessExpressionSyntax access
                || !MapMethods.TryGetValue(access.Name.Identifier.ValueText, out var verb)
                || call.ArgumentList.Arguments.Count == 0
                || StringValue(call.ArgumentList.Arguments[0].Expression) is not { } template)
                continue;

            var prefix = ReceiverPrefix(access.Expression, groups);
            var handler = call.ArgumentList.Arguments.Count > 1
                ? call.ArgumentList.Arguments[1].Expression switch
                {
                    IdentifierNameSyntax id => id.Identifier.ValueText,
                    MemberAccessExpressionSyntax m => m.Name.Identifier.ValueText,
                    _ => "lambda",
                }
                : "";
            var doc = ChainedDescription(call)
                      ?? (methodDocs.TryGetValue(handler, out var d) ? d : "");
            var line = call.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
            yield return new DiscoveredRoute(verb, RouteTemplate.Normalize(RouteTemplate.Join(prefix, template)),
                                             file, line, handler, doc);
        }
    }

    /// <summary>Map <c>var api = app.MapGroup("/api")</c> variable names to their full prefix.</summary>
    private static Dictionary<string, string> GroupPrefixes(CompilationUnitSyntax root)
    {
        var groups = new Dictionary<string, string>(StringComparer.Ordinal);
        // Declarations appear in source order, so a nested group's parent is already known.
        foreach (var declarator in root.DescendantNodes().OfType<VariableDeclaratorSyntax>())
        {
            if (declarator.Initializer?.Value is InvocationExpressionSyntax init
                && GroupPrefix(init, groups) is { } prefix)
                groups[declarator.Identifier.ValueText] = prefix;
        }
        return groups;
    }

    private static string? GroupPrefix(InvocationExpressionSyntax call, Dictionary<string, string> groups)
    {
        // Allow fluent tails such as app.MapGroup("/api").WithTags("x").RequireAuthorization()
        while (call.Expression is MemberAccessExpressionSyntax { Name.Identifier.ValueText: not "MapGroup" } tail
               && tail.Expression is InvocationExpressionSyntax inner)
            call = inner;
        if (call.Expression is not MemberAccessExpressionSyntax { Name.Identifier.ValueText: "MapGroup" } access
            || call.ArgumentList.Arguments.Count == 0
            || StringValue(call.ArgumentList.Arguments[0].Expression) is not { } template)
            return null;
        return RouteTemplate.Join(ReceiverPrefix(access.Expression, groups), template);
    }

    private static string ReceiverPrefix(ExpressionSyntax receiver, Dictionary<string, string> groups) => receiver switch
    {
        IdentifierNameSyntax id when groups.TryGetValue(id.Identifier.ValueText, out var prefix) => prefix,
        InvocationExpressionSyntax call => GroupPrefix(call, groups) ?? "",
        _ => "",
    };

    /// <summary>Text from a fluent <c>.WithSummary("...")</c> or <c>.WithDescription("...")</c> after a Map call.</summary>
    private static string? ChainedDescription(InvocationExpressionSyntax call)
    {
        SyntaxNode node = call;
        while (node.Parent is MemberAccessExpressionSyntax access && access.Parent is InvocationExpressionSyntax outer)
        {
            if (access.Name.Identifier.ValueText is "WithSummary" or "WithDescription"
                && outer.ArgumentList.Arguments.Count > 0
                && StringValue(outer.ArgumentList.Arguments[0].Expression) is { } text)
                return text;
            node = outer;
        }
        return null;
    }

    // ------------------------------------------------------------------ syntax helpers

    private static IEnumerable<AttributeSyntax> Attributes(SyntaxList<AttributeListSyntax> lists, string name) =>
        lists.SelectMany(l => l.Attributes).Where(a => SimpleName(a.Name.ToString()) == name);

    /// <summary><c>Microsoft.AspNetCore.Mvc.HttpGetAttribute</c> -> <c>HttpGet</c>.</summary>
    private static string SimpleName(string name)
    {
        var simple = name[(name.LastIndexOf('.') + 1)..];
        var generic = simple.IndexOf('<');
        if (generic >= 0)
            simple = simple[..generic];
        return simple.EndsWith("Attribute", StringComparison.Ordinal) ? simple[..^"Attribute".Length] : simple;
    }

    /// <summary>The route template argument: first positional string, or <c>template:</c>.</summary>
    private static string? FirstString(AttributeSyntax attr) =>
        attr.ArgumentList?.Arguments
            .Where(a => a.NameEquals is null && (a.NameColon is null || a.NameColon.Name.Identifier.ValueText == "template"))
            .Select(a => StringValue(a.Expression))
            .FirstOrDefault();

    private static IEnumerable<string> PositionalStrings(AttributeSyntax attr) =>
        attr.ArgumentList?.Arguments
            .Where(a => a.NameEquals is null && a.NameColon is null)
            .Select(a => StringValue(a.Expression))
            .OfType<string>() ?? [];

    private static string? StringValue(ExpressionSyntax expression) =>
        expression is LiteralExpressionSyntax literal && literal.IsKind(SyntaxKind.StringLiteralExpression)
            ? literal.Token.ValueText
            : null;

    private static string XmlSummary(SyntaxNode node)
    {
        var summary = node.GetLeadingTrivia()
            .Select(t => t.GetStructure())
            .OfType<DocumentationCommentTriviaSyntax>()
            .SelectMany(d => d.Content.OfType<XmlElementSyntax>())
            .FirstOrDefault(e => e.StartTag.Name.LocalName.ValueText == "summary");
        if (summary is null)
            return "";
        var text = string.Concat(summary.Content.Select(c => c switch
        {
            XmlTextSyntax t => string.Concat(t.TextTokens.Select(tok => tok.ValueText)),
            XmlEmptyElementSyntax e => " " + (e.Attributes.OfType<XmlCrefAttributeSyntax>().FirstOrDefault()?.Cref.ToString() ?? "") + " ",
            XmlElementSyntax e => string.Concat(e.Content.OfType<XmlTextSyntax>().SelectMany(t => t.TextTokens).Select(tok => tok.ValueText)),
            _ => "",
        }));
        return Whitespace().Replace(text, " ").Trim();
    }
}
