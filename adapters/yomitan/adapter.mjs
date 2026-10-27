// Yomitan's scanning parser, raw: one unit per term it takes from a sentence.
//
// The scanning parser is the backend's `parseText` with `useInternalParser`,
// which the search page uses to split a sentence into terms: at each position
// it looks up the next `scanLength` characters with Translator.findTerms
// (deinflecting, exact match), takes the longest term found, and moves past
// it; a character that starts no term is skipped. This runs Yomitan's own
// code from a pinned checkout (README.md): its DictionaryImporter loads the
// JMdict into an in-memory IndexedDB (fake-indexeddb), as its test fixtures
// do, and Backend.prototype._onApiParseText and _textParseScanning run on a
// stand-in for the Backend that holds the Translator and the default profile
// options, as its own test/backend-mecab-parse.test.js does. The Backend
// itself is never constructed: its constructor wires the extension's browser
// APIs.
//
// Yomitan's parse result is a list of segment groups. A group with headwords
// is a term; the others are the text it skipped, the gaps. For each term:
//
// - form, form_reading: the headword of the first dictionary entry
//   findTerms returned for that position, the one whose furigana the parser
//   shows.
// - reading: the parser's furigana, each segment's reading or, for kana, its
//   text, in hiragana.
// - entries: that entry's JMdict sequence number. Yomitan reads a negative
//   sequence as none; jmdict-yomitan writes one for a search-only spelling
//   (すご〜い), the negated seq of the entry it belongs to, so that seq is
//   output.
// - kind: from that row's part-of-speech tags, in the dictionary's order.
//   A row without any (a search-only spelling, a "forms" row) has no kind.
//
// A reading that is not kana is left out: Yomitan has none to give. A
// search-only kanji spelling has no reading in the dictionary, which Yomitan
// fills with the term, and the furigana split gives none when the text and
// the headword differ (10月 for １０月, はMe for 羽目).

import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync} from 'node:fs';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {createInterface} from 'node:readline';
import {pathToFileURL} from 'node:url';

const HOME = process.env.YOMITAN_HOME ?? join(process.env.MONOSASHI_CACHE ?? join(homedir(), '.cache', 'monosashi'), 'adapters', 'yomitan');
const SRC = join(HOME, 'src');
const DICTIONARY = join(HOME, 'JMdict_english.zip');

// Yomitan's library code may log; stdout carries only the contract's lines.
console.log = console.info = console.debug = console.warn = console.dir = console.table = console.error;

if (!existsSync(join(SRC, 'ext', 'lib', 'zip.js')) || !existsSync(join(SRC, 'node_modules', 'fake-indexeddb')) || !existsSync(DICTIONARY)) {
    console.error(`yomitan adapter: no Yomitan build or dictionary in ${HOME}; see adapters/yomitan/README.md`);
    process.exit(1);
}

/** @param {string} path a module of the Yomitan checkout */
const yomitan = (path) => import(pathToFileURL(join(SRC, path)).href);

// The JMdict tags ichiran's adapter maps too; any other part of speech is a word.
const KINDS = new Map([
    ['prt', 'particle'],
    ['aux', 'auxiliary'],
    ['aux-v', 'auxiliary'],
    ['aux-adj', 'auxiliary'],
    ['pref', 'prefix'],
    ['suf', 'suffix'],
    ['int', 'interjection'],
    ['exp', 'expression'],
]);
const COPULA = new Set(['cop', 'cop-da']);

const {Uint8ArrayReader, ZipReader, TextWriter} = await yomitan('ext/lib/zip.js');

const file = readFileSync(DICTIONARY);
const archive = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength);

async function dictionaryIndex() {
    const zip = new ZipReader(new Uint8ArrayReader(new Uint8Array(archive)));
    const entry = (await zip.getEntries()).find((e) => e.filename === 'index.json');
    const index = JSON.parse(await entry.getData(new TextWriter()));
    await zip.close();
    return index;
}

function git(...args) {
    return execFileSync('git', ['-C', SRC, ...args], {encoding: 'utf8'}).trim();
}

if (process.argv.includes('--describe')) {
    const index = await dictionaryIndex();
    const date = /\d{4}-\d{2}-\d{2}/.exec(index.revision);
    process.stdout.write(JSON.stringify({
        name: 'yomitan',
        version: `Yomitan ${git('describe', '--tags', '--always')}`,
        commit: git('rev-parse', 'HEAD'),
        dictionary: `${index.title} (jmdict-yomitan, JMdict_english.zip)`,
        dictionary_date: date === null ? 'unknown' : date[0],
        partition: true,
        fields: ['form', 'reading', 'form_reading', 'entries', 'kind'],
    }) + '\n');
    process.exit(0);
}

// The globals Yomitan's tests stub for its database and translator
// (test/fixtures/translator-test.js, test/utilities/database.js).
const {IDBKeyRange, indexedDB} = await yomitan('node_modules/fake-indexeddb/build/esm/index.js');
const mocks = await yomitan('test/mocks/common.js');
Object.assign(globalThis, {indexedDB, IDBKeyRange, fetch: mocks.fetch, chrome: mocks.chrome});

const {DictionaryDatabase} = await yomitan('ext/js/dictionary/dictionary-database.js');
const {DictionaryImporter} = await yomitan('ext/js/dictionary/dictionary-importer.js');
const {DictionaryImporterMediaLoader} = await yomitan('test/mocks/dictionary-importer-media-loader.js');
const {Translator} = await yomitan('ext/js/language/translator.js');
const {Backend} = await yomitan('ext/js/background/backend.js');
const {OptionsUtil} = await yomitan('ext/js/data/options-util.js');
const {CacheMap} = await yomitan('ext/js/general/cache-map.js');
const {DictionaryController} = await yomitan('ext/js/pages/settings/dictionary-controller.js');
const {convertHalfWidthKanaToFullWidth, convertKatakanaToHiragana, isCodePointKana} = await yomitan('ext/js/language/ja/japanese.js');

// After the imports, as setupStubs() does: zip.js must not see a Worker when
// it loads, and the database starts its media worker only outside one.
globalThis.self = {constructor: {name: 'Window'}};
globalThis.Worker = function Worker() { return {addEventListener: () => {}, terminate: () => {}}; };

const database = new DictionaryDatabase();
await database.prepare();
const optionsUtil = new OptionsUtil();
await optionsUtil.prepare();
const {errors, result} = await new DictionaryImporter(new DictionaryImporterMediaLoader()).importDictionary(
    database,
    archive,
    {prefixWildcardsSupported: optionsUtil.getDefault().global.database.prefixWildcardsSupported, yomitanVersion: '0.0.0.0'},
);
if (result === null || errors.length > 0) {
    throw new Error(`Yomitan could not import ${DICTIONARY}: ${errors.map(String).join('; ')}`);
}

// A fresh profile after the dictionary is imported: the settings page adds it
// with its defaults and, as it is sequenced, makes it the main dictionary.
const options = optionsUtil.getDefault().profiles[0].options;
options.dictionaries.push(DictionaryController.createDefaultDictionarySettings(result.title, true, result.styles));
if (result.sequenced && options.general.mainDictionary === '') { options.general.mainDictionary = result.title; }

const translator = new Translator(database);
translator.prepare();

// What findTerms returned for each text the parser looked up, for the
// sentence being parsed; the parser keeps only the headword and furigana.
/** @type {Map<string, import('translator').FindTermsResult>} */
const lookups = new Map();
const backend = {
    _translator: {
        async findTerms(mode, text, findTermsOptions) {
            const found = await translator.findTerms(mode, text, findTermsOptions);
            lookups.set(text, found);
            return found;
        },
    },
    _textParseCache: new CacheMap(10000, 3600000),
    _getProfileOptions: () => options,
    _getTranslatorFindTermsOptions: Backend.prototype._getTranslatorFindTermsOptions,
    _getTranslatorEnabledDictionaryMap: Backend.prototype._getTranslatorEnabledDictionaryMap,
    _getTranslatorTextReplacements: Backend.prototype._getTranslatorTextReplacements,
    _textParseScanning: Backend.prototype._textParseScanning,
};
const enabledDictionaries = Backend.prototype._getTranslatorEnabledDictionaryMap.call(backend, options);

/** @type {Map<string, string>} */
const tagCategories = new Map();

/** The database row of a dictionary entry: its definition tags in order and its raw sequence. */
async function databaseRow(term, id) {
    const rows = await database.findTermsBulk([term], enabledDictionaries, 'exact');
    const row = rows.find((r) => r.id === id);
    if (typeof row === 'undefined') { throw new Error(`no database row ${id} for ${term}`); }
    const unknown = row.definitionTags.filter((name) => !tagCategories.has(name));
    if (unknown.length > 0) {
        const tags = await database.findTagMetaBulk(unknown.map((name) => ({query: name, dictionary: row.dictionary})));
        unknown.forEach((name, i) => tagCategories.set(name, tags[i]?.category ?? ''));
    }
    return row;
}

function kindOf(definitionTags) {
    const pos = definitionTags.filter((name) => name === 'exp' || tagCategories.get(name) === 'partOfSpeech');
    if (pos.length === 0) { return null; }
    if (pos.some((name) => COPULA.has(name))) { return 'copula'; }
    return KINDS.get(pos[0]) ?? 'word';
}

/** Kana as hiragana, keeping ー and 〜; null for anything else, which is no reading. */
function hiragana(text) {
    const kana = convertHalfWidthKanaToFullWidth(text);
    for (const ch of kana) {
        if (ch !== '〜' && !isCodePointKana(ch.codePointAt(0))) { return null; }
    }
    return convertKatakanaToHiragana(kana, true);
}

// Characters that never belong to a unit (monosashi.kana.is_symbol).
const isSymbol = (ch) => ch !== 'ー' && ch !== '〜' && (/[\p{P}\p{S}\p{Z}]/u.test(ch) || ch === '・');

async function analyze(text) {
    lookups.clear();
    const scanLength = options.scanning.length;
    const [parse] = await Backend.prototype._onApiParseText.call(backend, {
        text,
        optionsContext: {},
        scanLength,
        useInternalParser: true,
        useMecabParser: false,
        useAllFrequencyDictionaries: options.parsing.useAllFrequencyDictionaries,
    });
    const units = [];
    let at = 0; // UTF-16
    let codePoints = 0;
    for (const group of parse.content) {
        const surface = group.map((segment) => segment.text).join('');
        const start = codePoints;
        codePoints += [...surface].length;
        const position = at;
        at += surface.length;
        if (!('headwords' in group[0])) { continue; } // a gap
        if ([...surface].every(isSymbol)) { continue; }
        const found = lookups.get(text.substring(position, position + scanLength));
        if (typeof found === 'undefined' || text.substring(position, position + found.originalTextLength) !== surface) {
            throw new Error(`Yomitan's term ${JSON.stringify(surface)} at ${position} is not the text it looked up`);
        }
        const [entry] = found.dictionaryEntries;
        const [{term, reading}] = entry.headwords;
        const row = await databaseRow(term, entry.definitions[0].id);
        const unit = {start, end: codePoints, surface, form: term};
        const surfaceReading = hiragana(group.map((segment) => segment.reading || segment.text).join(''));
        if (surfaceReading !== null) { unit.reading = surfaceReading; }
        const formReading = hiragana(reading);
        if (formReading !== null) { unit.form_reading = formReading; }
        // -1 is the database's own "no sequence"; any other negative one is jmdict-yomitan's.
        if (row.sequence !== -1) { unit.entries = [Math.abs(row.sequence)]; }
        const kind = kindOf(row.definitionTags);
        if (kind !== null) { unit.kind = kind; }
        units.push(unit);
    }
    return units;
}

for await (const line of createInterface({input: process.stdin, crlfDelay: Infinity})) {
    if (line.trim() === '') { continue; }
    const request = JSON.parse(line);
    const started = performance.now();
    let reply;
    try {
        const units = await analyze(request.text);
        reply = {id: request.id, units, ms: performance.now() - started};
    } catch (e) {
        reply = {id: request.id, error: `${e?.name ?? 'Error'}: ${e?.message ?? e}`};
    }
    process.stdout.write(JSON.stringify(reply) + '\n');
}
