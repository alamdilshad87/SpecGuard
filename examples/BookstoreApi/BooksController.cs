// A C# implementation of examples/bookstore-v1.yaml, used to demo drift detection
// for ASP.NET Core code. Scan it against bookstore-v2.yaml to see drift.
using Microsoft.AspNetCore.Mvc;

namespace BookstoreApi.Controllers;

public enum Genre { Fiction, Science, History }

public record NewBook(string Title, string Author, decimal? Price, Genre? Genre);

public record Book(int Id, string Title, string Author, decimal? Price, Genre? Genre);

[ApiController]
[Route("[controller]")]
public class BooksController : ControllerBase
{
    private static readonly Dictionary<int, Book> Books = new()
    {
        [1] = new Book(1, "Dune", "Frank Herbert", 9.99m, Genre.Fiction),
    };

    /// <summary>List books, optionally filtered by genre.</summary>
    [HttpGet]
    public ActionResult<IEnumerable<Book>> List([FromQuery] int? limit, [FromQuery] Genre? genre)
    {
        var books = Books.Values.Where(b => genre is null || b.Genre == genre);
        return Ok(limit is null ? books : books.Take(limit.Value));
    }

    /// <summary>Create a book. Titles must be 1-200 characters.</summary>
    [HttpPost]
    public ActionResult<Book> Create(NewBook book)
    {
        var id = Books.Count == 0 ? 1 : Books.Keys.Max() + 1;
        Books[id] = new Book(id, book.Title, book.Author, book.Price, book.Genre);
        return CreatedAtAction(nameof(Get), new { bookId = id }, Books[id]);
    }

    /// <summary>Get a single book by id.</summary>
    [HttpGet("{bookId:int}")]
    public ActionResult<Book> Get(int bookId) =>
        Books.TryGetValue(bookId, out var book) ? Ok(book) : NotFound();

    /// <summary>Delete a book. Returns 404 if it does not exist.</summary>
    [HttpDelete("{bookId:int}")]
    public IActionResult Delete(int bookId) =>
        Books.Remove(bookId) ? NoContent() : NotFound();
}
