FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Restore first so the layer is cached until project files change.
COPY src/SpecGuard.Scanner/SpecGuard.Scanner.csproj src/SpecGuard.Scanner/
COPY src/SpecGuard.Scanner.Api/SpecGuard.Scanner.Api.csproj src/SpecGuard.Scanner.Api/
RUN dotnet restore src/SpecGuard.Scanner.Api/SpecGuard.Scanner.Api.csproj

COPY src/ src/
RUN dotnet publish src/SpecGuard.Scanner.Api/SpecGuard.Scanner.Api.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app .
USER $APP_UID
EXPOSE 8080
ENTRYPOINT ["dotnet", "SpecGuard.Scanner.Api.dll"]
