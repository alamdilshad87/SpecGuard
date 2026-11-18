"""A small implementation of examples/bookstore-v1.yaml to run SpecGuard tests against.

    uvicorn mock_bookstore:app --port 9000
"""
from enum import Enum

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Bookstore API (demo)", version="1.0.0")


@app.exception_handler(RequestValidationError)
async def validation_as_400(_, exc: RequestValidationError):
    # The spec documents 400 for invalid input, so map FastAPI's 422 to 400.
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


class Genre(str, Enum):
    fiction = "fiction"
    science = "science"
    history = "history"


class NewBook(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    author: str
    price: float | None = Field(default=None, ge=0)
    genre: Genre | None = None


class Book(NewBook):
    id: int


BOOKS: dict[int, Book] = {1: Book(id=1, title="Dune", author="Frank Herbert", price=9.99, genre=Genre.fiction)}


@app.get("/books", response_model=list[Book])
def list_books(limit: int | None = Query(default=None, ge=1, le=100), genre: Genre | None = None):
    books = [b for b in BOOKS.values() if genre is None or b.genre == genre]
    return books[:limit] if limit else books


@app.post("/books", response_model=Book, status_code=201)
def create_book(book: NewBook):
    new_id = max(BOOKS, default=0) + 1
    BOOKS[new_id] = Book(id=new_id, **book.model_dump())
    return BOOKS[new_id]


@app.get("/books/{book_id}", response_model=Book)
def get_book(book_id: int):
    if book_id not in BOOKS:
        raise HTTPException(404, "Book not found")
    return BOOKS[book_id]


@app.delete("/books/{book_id}", status_code=204)
def delete_book(book_id: int):
    if BOOKS.pop(book_id, None) is None:
        raise HTTPException(404, "Book not found")
    return Response(status_code=204)
