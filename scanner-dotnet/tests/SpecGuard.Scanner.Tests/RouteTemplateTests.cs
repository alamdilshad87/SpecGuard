using SpecGuard.Scanner;

namespace SpecGuard.Scanner.Tests;

public class RouteTemplateTests
{
    [Theory]
    [InlineData("api/books", "{id}", "api/books/{id}")]
    [InlineData("api/books/", "", "api/books/")]
    [InlineData("", "health", "health")]
    [InlineData("api/books", "/absolute", "/absolute")]
    [InlineData("api/books", "~/root", "/root")]
    public void Combine_follows_aspnet_rules(string prefix, string template, string expected) =>
        Assert.Equal(expected, RouteTemplate.Combine(prefix, template));

    [Theory]
    [InlineData("/api", "/carts", "/api/carts")]
    [InlineData("/api/", "carts", "/api/carts")]
    [InlineData("", "/carts", "/carts")]
    public void Join_keeps_group_prefix_for_rooted_templates(string prefix, string template, string expected) =>
        Assert.Equal(expected, RouteTemplate.Join(prefix, template));

    [Theory]
    [InlineData("api/[controller]/{id:int}", "/api/books/{id}")]
    [InlineData("api/[controller]/[action]", "/api/books/search")]
    [InlineData("files/{*path}", "/files/{path}")]
    [InlineData("blog/{**slug}", "/blog/{slug}")]
    [InlineData("items/{id:int:min(1)}/{page?}", "/items/{id}/{page}")]
    [InlineData("items/{sort=name}", "/items/{sort}")]
    [InlineData("//double//slash/", "/double/slash")]
    [InlineData("", "/")]
    public void Normalize_produces_openapi_paths(string template, string expected) =>
        Assert.Equal(expected, RouteTemplate.Normalize(template, controller: "Books", action: "Search"));
}
