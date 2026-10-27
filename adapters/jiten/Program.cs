// Jiten's parser, raw: one unit per word Jiten.Parser.Parser.ParseText returns.
//
// This runs Jiten's own code from a pinned checkout (README.md), built into
// the monosashi-jiten-main container next to Jiten's CLI, against the
// Postgres database Jiten's CLI imported and the Redis cache the parser needs.
// It starts the parser the way Jiten's API does (Parser.WarmupAsync), then
// parses each sentence and places the words the way the API's
// GET /vocabulary/parse does: ParseText, then TokenPositionHelper (compiled in
// from Jiten.Api) finds each word's text after the previous one, tolerating
// the ー and line breaks the parser drops; a word it cannot find is left out,
// as the endpoint leaves it out. The one difference: the search runs over the
// text with ASCII digits made fullwidth, as the parser makes them before
// Sudachi sees them, so a word with a digit is found. Offsets are converted
// to code points, with the surface taken from the input.
//
// ParseText attempts the whole text, so this is a partition. What Jiten does
// not resolve to a dictionary word (symbols, but also text it cannot analyse)
// is not in its output, so it scores as a gap. A word that is only symbols is
// not output either. For each word:
//
// - form: the text of the entry's form Jiten chose (WordId + ReadingIndex in
//   jmdict."WordForms"), the dictionary spelling.
// - form_reading: that form's reading as Jiten's API reads it: the forms
//   loaded as WordFormHelper.LoadWordForms loads them, with
//   RubyTextHelper.EnrichForms inferring furigana for a kanji form that has
//   none from the entry's kana forms, then a kana form's own text, or a kanji
//   form's RubyTextHelper.KanaFromRubyText (始[はじ]める: はじめる), as
//   UserController does; left out when a kanji in it still has no furigana.
// - entries: the WordId, unless it is one of Jiten's own words. Jiten
//   imports each JMdict entry with its ent_seq as the WordId, and then each
//   JMnedict entry whose ent_seq JMdict does not already have, merging the
//   JMnedict entries that share their first spelling into the first of them.
//   Both dictionaries number their entries below 8,000,000 (JMnedict from
//   5,000,000), apart from their date records (9999999, 9999990); Jiten's own
//   words (でした, こうする, ...) start at 8,000,000. Those get none.
// - kind: from the parts of speech of the entry's first sense, as the ichiran
//   adapter maps them: cop anywhere makes a copula, otherwise the first tag
//   decides (prt particle, aux, aux-v and aux-adj auxiliary, pref prefix, suf
//   suffix, int interjection, exp expression, anything else a word). A word in
//   JMnedict's range (5,000,000 and up) whose first sense carries only name
//   types is a name; below it, JMdict's own tags decide (its unc, unclassified,
//   is no name).
//
// There is no reading: Jiten's parse output has none for the text (the API's
// word is its WordId, ReadingIndex, text and conjugations). DeckWord's
// SudachiReading, which the parser keeps to score forms, is the reading of the
// first Sudachi token of a word Jiten built from several (でも: で), so it is
// not the word's.

using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Jiten.Api.Helpers;
using Jiten.Core;
using Jiten.Core.Data;
using Jiten.Core.Data.JMDict;
using Jiten.Core.Utils;
using Jiten.Parser;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Npgsql;

// Jiten writes its own messages with Console.WriteLine; stdout carries only the contract's lines.
var stdout = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
Console.SetOut(Console.Error);

// Jiten's own words start here (JmDictHelper.GetCustomWords); JMdict's and JMnedict's ent_seqs are below.
const int FirstJitenWordId = 8_000_000;
// JMnedict's ent_seqs start here, the range Jiten's own code treats as names (JmDictHelper.SyncJmDict).
const int FirstJmnedictId = 5_000_000;

var jsonOptions = new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

// The configuration Jiten's CLI reads (CliContext.Create): the settings file, then the environment.
var configuration = new ConfigurationBuilder()
                    .SetBasePath(Directory.GetCurrentDirectory())
                    .AddJsonFile(Path.Combine("Shared", "sharedsettings.json"), optional: true)
                    .AddEnvironmentVariables()
                    .Build();
var connectionString = configuration.GetConnectionString("JitenDatabase")!;

if (args.Contains("--describe"))
{
    stdout.WriteLine(new JsonObject
    {
        ["name"] = "jiten",
        ["version"] = $"Jiten {Commit()[..8]}, parser revision {ParseVersion.ParserRevision}",
        ["commit"] = Commit(),
        // The parser reads jiten.moe's corpus frequency ranks and word origins, which are not
        // public: here those tables are empty (README.md).
        ["dictionary"] = $"JMdict and JMnedict as Jiten imports them, with SudachiDict full {SudachiDictionaryVersion()} and Jiten's user dictionary; without jiten.moe's corpus frequency ranks and word origins (not public)",
        ["dictionary_date"] = await JmdictDate(),
        ["partition"] = true,
        ["fields"] = new JsonArray("form", "form_reading", "entries", "kind"),
    }.ToJsonString(jsonOptions));
    stdout.Flush();
    return;
}

var dbOptions = new DbContextOptionsBuilder<JitenDbContext>()
                .UseNpgsql(connectionString, o => o.UseQuerySplittingBehavior(QuerySplittingBehavior.SplitQuery))
                .Options;
IDbContextFactory<JitenDbContext> factory = new ContextFactory(dbOptions);

await Parser.WarmupAsync(factory, Console.Error.WriteLine);

var entryCache = new Dictionary<int, Entry>();

using var stdin = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
while (await stdin.ReadLineAsync() is { } line)
{
    if (string.IsNullOrWhiteSpace(line)) continue;
    var request = JsonNode.Parse(line)!.AsObject();
    var id = request["id"]!.DeepClone();
    var started = Stopwatch.StartNew();
    JsonObject reply;
    try
    {
        var units = await Analyze(id.ToJsonString(jsonOptions), request["text"]!.GetValue<string>());
        reply = new JsonObject { ["id"] = id, ["units"] = units, ["ms"] = started.Elapsed.TotalMilliseconds };
    }
    catch (Exception e)
    {
        reply = new JsonObject { ["id"] = id, ["error"] = $"{e.GetType().Name}: {e.Message}" };
    }

    stdout.WriteLine(reply.ToJsonString(jsonOptions));
    stdout.Flush();
}

return;

async Task<JsonArray> Analyze(string id, string text)
{
    var (cleanText, _) = FuriganaHintExtractor.Extract(text);
    if (cleanText != text)
        throw new InvalidOperationException("the text holds Jiten's furigana markup ({base'reading}), which Jiten parses without it");

    var words = await Parser.ParseText(factory, text);

    // VocabularyController.BuildParseResult: each word is found after the previous one. The
    // parser turns ASCII digits fullwidth before Sudachi sees them (PreprocessText), one char
    // for one, so the words are found in the text with that done too; the endpoint, which
    // searches the raw text, loses 1人 (parsed as １人) there.
    var searched = text.ToFullWidthDigits();
    var placed = new List<(DeckWord Word, int Position, int Length)>();
    int current = 0;
    foreach (var word in words)
    {
        var (position, length) = TokenPositionHelper.FindTokenInSource(searched, word.OriginalText, current);
        if (position < 0)
        {
            Console.Error.WriteLine($"jiten adapter: record {id}: {JsonSerializer.Serialize(word.OriginalText, jsonOptions)} is not in the text after {current}; left out");
            continue;
        }

        placed.Add((word, position, length));
        current = position + length;
    }

    await LoadEntries(placed.Select(p => p.Word.WordId));

    // Code point offsets for UTF-16 ones: 𠮷 is one code point, two chars.
    var codePoints = new int[text.Length + 1];
    for (int i = 0, n = 0; i <= text.Length; i++)
    {
        codePoints[i] = n;
        if (i < text.Length && !char.IsHighSurrogate(text[i])) n++;
    }

    var units = new JsonArray();
    foreach (var (word, position, length) in placed)
    {
        var surface = text.Substring(position, length);
        if (surface.EnumerateRunes().All(IsSymbol)) continue;

        var unit = new JsonObject
        {
            ["start"] = codePoints[position], ["end"] = codePoints[position + length], ["surface"] = surface,
        };
        entryCache.TryGetValue(word.WordId, out var entry);
        if (entry != null && entry.Forms.TryGetValue(word.ReadingIndex, out var form))
        {
            unit["form"] = form.Text;
            if (Hiragana(form.Reading) is { } formReading) unit["form_reading"] = formReading;
        }

        if (word.WordId is > 0 and < FirstJitenWordId) unit["entries"] = new JsonArray(word.WordId);
        if (entry?.Kind is { } kind) unit["kind"] = kind;
        units.Add(unit);
    }

    return units;
}

async Task LoadEntries(IEnumerable<int> wordIds)
{
    var missing = wordIds.Where(id => !entryCache.ContainsKey(id)).Distinct().ToList();
    if (missing.Count == 0) return;

    await using var context = await factory.CreateDbContextAsync();
    // WordFormHelper.LoadWordForms (Jiten.Api), the loader Jiten's own readers use.
    var forms = await context.WordForms.AsNoTracking()
                             .Where(f => missing.Contains(f.WordId))
                             .ToDictionaryAsync(f => (f.WordId, f.ReadingIndex));
    RubyTextHelper.EnrichForms(forms);
    var senses = await context.Definitions.AsNoTracking()
                              .Where(d => missing.Contains(d.WordId))
                              .OrderBy(d => d.SenseIndex).ThenBy(d => d.DefinitionId)
                              .Select(d => new { d.WordId, d.Pos, d.PartsOfSpeech })
                              .ToListAsync();
    foreach (var id in missing)
    {
        var first = senses.FirstOrDefault(s => s.WordId == id);
        entryCache[id] = new Entry(
            forms.Values.Where(f => f.WordId == id).ToDictionary(
                f => (byte)f.ReadingIndex,
                f => new Form(f.Text, f.FormType == JmDictFormType.KanaForm ? f.Text : RubyTextHelper.KanaFromRubyText(f.RubyText))),
            first == null ? null : KindOf(id, first.Pos.Count > 0 ? first.Pos : first.PartsOfSpeech));
    }
}

string Commit() => File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "..", "jiten-commit")).Trim();

// The description in the system dictionary's header: SudachiDict writes its release date there.
string SudachiDictionaryVersion()
{
    using var file = File.OpenRead(configuration.GetValue<string>("DictionaryPath")!);
    var header = new byte[16 + 256];
    file.ReadExactly(header);
    return Encoding.UTF8.GetString(header, 16, 256).TrimEnd('\0');
}

// JMdict's own record of its date, entry 9999999, which Jiten imports with the rest.
async Task<string> JmdictDate()
{
    await using var connection = new NpgsqlConnection(connectionString);
    await connection.OpenAsync();
    await using var command = new NpgsqlCommand(
        """SELECT "EnglishMeanings"[1] FROM jmdict."Definitions" WHERE "WordId" = 9999999 ORDER BY "DefinitionId" LIMIT 1""",
        connection);
    var gloss = await command.ExecuteScalarAsync() as string ?? "";
    var date = Regex.Match(gloss, @"\d{4}-\d{2}-\d{2}");
    return date.Success ? date.Value : "unknown";
}

static string? KindOf(int wordId, List<string> tags)
{
    if (tags.Count == 0) return null;
    if (wordId >= FirstJmnedictId && tags.All(IsNameTag)) return "name";
    if (tags.Any(t => t is "cop" or "cop-da")) return "copula";
    return tags[0] switch
    {
        "prt" => "particle",
        "aux" or "aux-v" or "aux-adj" => "auxiliary",
        "pref" => "prefix",
        "suf" => "suffix",
        "int" => "interjection",
        "exp" => "expression",
        _ => "word",
    };
}

// The name types JmDictHelper.LoadNameOnlyWordIds counts as names, and "name", which the
// JMnedict import gives a sense without a name type. The list includes unc, which in JMdict
// is "unclassified"; KindOf asks only of words in JMnedict's range.
static bool IsNameTag(string tag) =>
    tag.StartsWith("name-", StringComparison.Ordinal) || tag is "name" or "company" or "given" or "place" or "person" or "product"
        or "ship" or "surname" or "unclass" or "station" or "group" or "char" or "creat" or "dei" or "doc" or "ev"
        or "fem" or "fict" or "leg" or "masc" or "myth" or "obj" or "organization" or "oth" or "relig" or "serv"
        or "work" or "unc";

// Kana as hiragana, keeping ー; null for anything else, which is no reading.
static string? Hiragana(string? text)
{
    if (string.IsNullOrEmpty(text) || !text.All(IsKana)) return null;
    return new string(text.Select(ch => ch is >= 'ァ' and <= 'ヶ' ? (char)(ch - 0x60) : ch).ToArray());
}

static bool IsKana(char ch) => ch is >= 'ぁ' and <= 'ゖ' or >= 'ゝ' and <= 'ゟ' or >= 'ァ' and <= 'ヺ' or >= 'ー' and <= 'ヿ';

// monosashi.kana.is_symbol: punctuation, symbols and spaces, but not ー or 〜; ・ is one.
static bool IsSymbol(Rune rune)
{
    if (rune.Value is 'ー' or '〜') return false;
    if (rune.Value == '・') return true;
    return Rune.GetUnicodeCategory(rune) switch
    {
        UnicodeCategory.ConnectorPunctuation or UnicodeCategory.DashPunctuation or UnicodeCategory.OpenPunctuation
            or UnicodeCategory.ClosePunctuation or UnicodeCategory.InitialQuotePunctuation
            or UnicodeCategory.FinalQuotePunctuation or UnicodeCategory.OtherPunctuation or UnicodeCategory.MathSymbol
            or UnicodeCategory.CurrencySymbol or UnicodeCategory.ModifierSymbol or UnicodeCategory.OtherSymbol
            or UnicodeCategory.SpaceSeparator or UnicodeCategory.LineSeparator or UnicodeCategory.ParagraphSeparator => true,
        _ => false,
    };
}

record Form(string Text, string? Reading);

record Entry(Dictionary<byte, Form> Forms, string? Kind);

sealed class ContextFactory(DbContextOptions<JitenDbContext> options) : IDbContextFactory<JitenDbContext>
{
    public JitenDbContext CreateDbContext() => new(options);
}
