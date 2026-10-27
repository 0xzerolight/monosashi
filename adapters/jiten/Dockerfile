# Jiten's CLI and the monosashi adapter, built from a pinned Jiten checkout
# (the `jiten` build context, README.md) the way Jiten's own
# Jiten.Cli/Dockerfile builds its CLI: .NET 9 SDK, Release, Shared/resources
# beside the binaries, the example settings as Shared/sharedsettings.json.
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
COPY --from=jiten . /src/jiten
RUN git -C /src/jiten rev-parse HEAD > /src/jiten-commit \
    && cp /src/jiten/Shared/sharedsettings.example.json /src/jiten/Shared/sharedsettings.json
RUN dotnet publish /src/jiten/Jiten.Cli/Jiten.Cli.csproj -c Release -o /app/cli
COPY MonosashiJiten.csproj Program.cs /src/adapter/
RUN dotnet publish /src/adapter/MonosashiJiten.csproj -c Release -o /app/adapter -p:JitenSrc=/src/jiten

FROM mcr.microsoft.com/dotnet/aspnet:9.0
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /app /app
COPY --from=build /src/jiten/Shared/resources /app/cli/resources
COPY --from=build /src/jiten/Shared/resources /app/adapter/resources
COPY --from=build /src/jiten/Shared/sharedsettings.json /app/Shared/sharedsettings.json
COPY --from=build /src/jiten/Jiten.Core/Data/JMDict/jmdict_dtd.xml /app/jmdict_dtd.xml
COPY --from=build /src/jiten-commit /app/jiten-commit
CMD ["sleep", "infinity"]
