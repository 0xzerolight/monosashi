# monosashi labeling spec

Version 0.5 (2026-10-17): 0.4 with the rulings on the questions labelers raised in the 994-record core run. The changelog is at the end. A rule change bumps the version, and records labeled under an older version fail validation until they are re-checked.

This spec says what a gold label means. Labelers follow it, `monosashi validate` enforces the parts a program can check, and the scorer compares tools against it. Where a rule here and a labeler's instinct disagree, the rule wins. Raise the disagreement as a spec question; don't label around it.

## 1. What a record is

A record is one sentence, already normalized (§2), and the units that cover it. Every character belongs to exactly one unit, except punctuation, symbols and spaces between units, which belong to none. Kanbun (classical Chinese in kanji order, read by kundoku) is out of scope: its reading lives in the reader, not the text, so no record holds it.

A unit may contain a space or symbol only where the writing splits one word: a line-break space (頑張 って), a comma between digit groups (44,276), a ― used as a length mark between kana (ナア――ンダ), Aozora's repeat mark ／＼ (そわ／＼した), and the separator inside one name (・, = or ＝, - or －, or a space: TIME SLIP黄金丸). A unit never starts or ends with one. Readings leave out the spaces, commas and separators, write the dash as ー, and spell out the repeat: そわ／＼した reads そわそわした. A kana iteration mark (ゝ ゞ ヽ ヾ) is part of the word and repeats the kana before it, voiced for ゞ and ヾ: いゝえ reads いいえ, みすゞ reads みすず.

A unit is what a learner would look up:

- an inflecting word together with its whole inflection chain;
- a JMdict entry, using the longest entry that fits the sentence;
- a name;
- a word JMdict lacks;
- a particle or other function word, which is a unit but never a flashcard.

Offsets count Unicode code points in the normalized text, from 0, with `end` exclusive. `text[start:end] == surface` for every unit.

## 2. Normalization

Gold text is normalized once, before labeling. Only three changes are made:

1. Unicode NFC.
2. Halfwidth katakana becomes fullwidth (ｶﾞﾝﾊﾞﾚ → ガンバレ).
3. Every tilde-like character (～ U+FF5E, ~, ∼, ˜) becomes 〜 U+301C, the character JMdict uses in its own spellings (すご〜い).

Nothing else changes. Fullwidth digits stay fullwidth, because JMdict spells １人暮らし with one, and ASCII stays ASCII (3つ). JMdict spells letters and digits fullwidth (３つ, ＣＤ), so spellings are compared after widening ASCII.

A 〜 that marks a range (10時〜12時) belongs to no unit, like punctuation. A 〜 right after kana stretches that word (すご〜い, あの〜) and is part of it.

## 3. Unit kinds

| kind | Card? | Entry ids | Use for |
|---|---|---|---|
| `word` | yes | JMdict, or none | content words, with their chains; auxiliaries and kanji-written particles that have an entry of their own (らしい, みたい, 位) |
| `expression` | yes | JMdict | units whose entries are tagged `exp` in JMdict: 気に入る, かもしれない, ですか, じゃない |
| `interjection` | yes (with no entry: no) | JMdict, or none | ああ, えっ, すげー (JMdict tags it exp + int), kana runs such as どおおお, stammered fragments (§4.8) |
| `name` | yes, but readings not scored | JMnedict, or none | people, places and other individuals JMdict does not list; a title, organization, event or facility only when JMnedict lists it or its name is coined (§4.6) |
| `particle` | no | none | は, が, を, に, の, と, も, よ, ね, か, って; kana particles JMdict also lists as another part of speech (なんて, ほど); fused pairs (にゃ, ちゃ) |
| `copula` | no | none | だ, です, である, じゃ and their past and polite forms (だった, でした, じゃった, であった) when no longer expression entry covers it; な after a na-adjective (大切な); に and で after a word JMdict tags adj-na (楽に, マジで); なら, だったら, でございます |
| `auxiliary` | no | none | an auxiliary with no entry of its own that no chain absorbed (せし, たる) |
| `prefix` | no | none | お, ご, 不, 無 when JMdict does not join them (§4.5) |
| `suffix` | no | none | さん, たち, 様, 的, and nouns bound to a host (市, 中, 頃), when JMdict does not join them (§4.5) |

The `exp` rule is mechanical. A unit whose entries include an exp-tagged one may be an `expression`. A unit whose entries are only expressions may not be a `word`. JMdict lists parts of speech per entry, across all its senses, so an entry that is also a noun, verb, adjective, adverb, pronoun, numeral, counter or conjunction (ちょっと, くしゃみ, 気に入る) is not only an expression: it may be either kind, and the two kinds are not a disagreement between labelers. An entry tagged both exp and int (すみません, すげー) may likewise be an `interjection` or an `expression`, and those two kinds are not a disagreement either. Nor are `word` and `interjection` on one entry tagged int beside a content part of speech (了解, おおきに). JMdict and JMnedict ids overlap, so a `name` unit's ids are JMnedict ids, and every other unit's ids are JMdict ids.

Borderline kinds:

- **Auxiliaries with an entry.** An auxiliary that JMdict lists as an entry of its own, left outside every chain, is a `word` with that entry, or an `expression` when the exp rule says so: らしい, べし, べき, ごとく, ごとき, みたい, そう 'looks like' after a na-adjective, っしょ, Kansai はる and まう, たまう, うる (得る), ござる. Grammar entries tagged as auxiliaries that win as the longest entry (なんだ, なんです, なのです, ようだ) are one unit too. `auxiliary` is only for a piece with no entry of its own, such as the classical せる, せし, たる, り and き (§4.7).
- **The copula.** に and で after a word JMdict tags adj-na in some sense are the copula's adverbial and te forms: 大量に, 楽に, 幸せそうに, みたいに, 的に and マジで end in a `copula` unit, like the な of 大切な. After anything else に and で are particles: で marking place, means or a limit (ペンで, だけで), and で after a noun predicate (徒歩3分程度で、). Conditional and polite forms (なら, ならば, だったら, やったら, でございます, であった, the classical なり and たり) are copula units too, unless they open a sentence or clause as a conjunction (§4.3). The copula's past and polite forms are copula units although JMdict lists だった (2819970) and じゃった as `exp` entries, and so is a lone じゃ (2851029): the longer expression entry in the table above means one that adds meaning beyond the copula, such as じゃない, ですか, だろう or でしょう.
- **Particles with another part of speech.** A particle written in kana stays a `particle` even when JMdict also tags its entry adv, conj or n (なんて, なんか, ほど, とか, でも, くらい, ばかり, さかい, じゃん, ねん), unless the sentence uses that other part of speech (なんか 'somehow', ほど 'extent', でも 'but' opening a sentence). A particle written in kanji (位, 等, 迄, 哉) is a `word` with its entry. A particle that is a whole utterance (ね as a reply) is an `interjection`, with its entry when a sense fits. An `exp` entry ending in a particle that §4.3 doesn't split is an `expression` (Kansai やんか); an entry tagged only as a particle stays a `particle` (じゃん, ねん, さかい).
- **Fusions.** A word fused with a particle (こりゃ, そりゃ, もなア, あらァ, いらあ) is one content unit. It takes the fused spelling's entry when one of its senses fits, and otherwise is a `word` with empty entries and the surface as its form. Either way it carries the `contraction` target and never `oov`, since its parts are listed. A particle pair fused into one syllable (にゃ, じゃ for では, ちゃ for ては, っちゃ) is a `particle`.

## 4. Where units begin and end

Find the correct analysis of the sentence first. Then, among analyses that are correct in context, apply these rules in order. This is not greedy string matching: はすごく is は|すごく, even though はす is a word. A rule that picks a dictionary entry applies only when one of that entry's senses fits the sentence; an entry whose senses don't fit is not a correct analysis.

### 4.1 Chains

A verb or adjective unit runs as far as the pinned deinflector carries its surface back to its dictionary form. Its `chain` lists the transforms that do so, dictionary form outward.

The deinflector is Yomitan's Japanese rule table (54 transforms, Yomitan commit e2ed450), vendored through anki_miner and never edited. Supplements sit beside it:

- **`-みる`**: てみる / でみる → て / で, an ichidan auxiliary.
- **て + auxiliary**: `-くる`, `-いく`, `-ある`, `-あげる`, `-くれる`, `-もらう` and `-ほしい`, for て / で followed by くる (来る), いく (行く, ゆく, with the contracted てく, てった and てってる), ある, あげる (上げる), くれる (呉れる), もらう (貰う) and ほしい (欲しい). Each auxiliary keeps its own conjugation, so the chain goes on past it: 見せてもらった is `-て, -もらう, -た`.
- **Kansai and colloquial forms**: `-ん (kansai)`, る → ん after godan verbs and する (わかん, すん); `-ない (kansai)`, ろない for ろい (おもろない); `volitional (short)`, こよ and しよ; `-ゃがる`, やがる after a contracted stem (行きゃがる). Other such forms (寒ない, くん, 行こ) fall under "Where the table stops".
- **One-kanji stems**: `continuative (kanji stem)`, the bare stem of a one-kanji ichidan verb whose spelling JMdict marks common (見 in 見ながら, 寝, 出, 居, 着). The table's continuative needs a kana before る, so it misses them (spec-27).

So these are all inside one unit:

- causative, passive, potential and the ra-nuki potential;
- negative, -た, -て, -ます, -たい, -ば, -たら, -たり;
- て + いる / しまう / おく / みる / くる / いく / ある / あげる / くれる / もらう / ほしい, and the contractions てる, ちゃう, ちまう, とく, てく;
- -すぎる, -そう, -がる, -やがる;
- the Kansai-ben forms in the table and the supplements.

**Where the table stops.** Transforms the table and the supplements lack end the chain, and what follows is a unit of its own (§4.7). Keep the entry and the dictionary form of a word JMdict has wherever the table and the supplements reach it. A form they can't reach at all is one word with empty entries, its dictionary form when the validator relates it to the surface and otherwise the surface as its form, tagged with what it is (`contraction`, `kansai`, `archaic-classical`) and never `oov`: いらあ, 恐かない, もろて, おっしゃい. A listed word or expression the table reaches only through a contraction it lacks (みてえ for みたい, 位え for くらい) takes the same fallback; only a contracted ている keeps an expression's entry (§4.3).

**A sentence-final particle stays out.** 買ってよ is 買って|よ, although the table could read てよ as the imperative of a contracted ている. The same holds whenever a following よ, ね, ねえ or ねぇ would join the chain only through a contracted -いる or -おく: やめとけ|よ, 待って|ねぇ. Choose by context, as §4 says.

**Chains against expressions.** Chains win only over an expression that starts inside them, and then the chain's boundaries hold: 行かなければならない is 行かなければ|ならない, not 行か|なければならない (spec-04). The same goes for ないことには, そうにない and ちゃいけない after a chain. After a conditional (なければ, ねば, なくては, にゃ), ならない is the expression 2083990 'must', with form ならない and the `grammar-expression` target; ならぬ, ならん and なりません are its search-only spellings, so their form is ならない too. ならなかった takes chain `-た`, as かもしれなかった does (§4.3). いけない after a conditional, と or ては is likewise the expression 1000730 with `grammar-expression` (しないと|いけない), and so is 違いない after に. ざるを得ない (2060970) after a chain ending in -ざる gives way to the chain, since no correct cut keeps it: 剃らざる|を|得なかった. After a vs noun, §4.2 splits せざるをえない off whole.

An expression entry that starts at or before the chain and contains all of it is one unit with split points, when one of its senses fits: 出てくる, 帰ってくる, 持っていく, お願いできますか, 知ったことではない, 経たぬうちに, と思ったら. やってきた 'have been doing' is not やってくる 'come along', so it is やる with chain `-て, -くる, -た`.

**Same span.** When a span is an inflected form of one word and also an entry of its own, JMdict's `exp` tag decides. An entry tagged `exp` is a lexicalized expression and wins when one of its senses fits: いけない (1000730), 堪らない, わけない, として. When none fits, the chain wins: 始まらない 'doesn't start' is 始まる + `negative`, not the idiom 'it's no use'. Any other entry loses to the chain when the inflected reading is the correct analysis: 得ない is 得る + `negative`, 切れない is 切れる + `negative`, すごく is すごい + `-く`, 見れる is 見る + `potential` (spec-19). A surface that reaches a godan verb and a vs-s verb with the same senses (付される: 付す, 付する) takes the godan form and lists both entries, the godan one first.

Two cases keep their own entry:

- **Nouns and adnominals.** A span used as a noun (before a case particle such as の, を, が, は, まで or から, or heading a phrase) or as an adnominal with an entry of its own takes that entry: 多くの, 多くを, 旅行の楽しみ, お土産選び, 千切りにした; 思わぬ, とんだ, ちゃんとした. An adnominal entry whose sense is only the verb's past or negative, the same test as for derived verbs, is that verb with its chain: 残った兵士 'the soldiers who remained' is 残る + `-た`, though JMdict lists 残った 'remaining'. Adverbial -く stays a chain when the adjective's sense gives its meaning (すごく, よく 'well'); an adverb entry with a sense the adjective lacks takes its own entry (よく 'often', 全く).
- **Derived verbs.** When the surface reaches both a verb with its own entry and that verb's base through a potential, passive or causative transform, the chain stops at the derived verb if one of its senses fits and is not just that voice of the base: 切れる 'break', 思える 'seem', 聞かせる 'tell', 開ける, くれる. Otherwise it runs to the base: 行われる 'be done' is 行う + `passive`, 使えない is 使う + `potential`, `negative`, and 見れる is 見る + `potential` (spec-19).

### 4.2 Noun + する

A noun whose entry is tagged `vs` joins a following する and its chain into one unit. The unit's entry is the noun and its form is the noun: 勉強している, with form 勉強 (spec-05). Bare 勉強する is one unit too, with an empty chain.

Only vs nouns join. Any other noun + する is two units, the noun and する with its chain (キャスティング|された), as §4.7 does for unlisted nouns. After a vs noun, し得る, すべき and せざるをえない split off: 処理し|得ない, 優先|すべき, 指揮|せざるをえない (1006510, `grammar-expression`). A する-verb entry (vs-s, vz) that spells the noun + する span wins over the noun + する when one of its senses fits: 相対していた is 相対する, read あいたいしていた (2437160). Honorific お + stem + する is prefix | stem | する: お|かけ|します.

### 4.3 The longest entry

Outside chains, a span that is one JMdict entry stays one unit even when its parts are words too, as long as one of the entry's senses fits the sentence. This covers compounds such as 一人暮らし and lexicalized phrases such as 元も子もない and 気に入る. It also covers grammar expressions such as かもしれない, ですか and じゃない. An entry whose senses don't fit is labeled by its parts: ということだ is listed only for hearsay and conjecture ('I've heard that', 'it appears as if'), so where the sentence means 'that is to say' it is という|こと|だ.

When the parts are themselves words, record the boundaries between them as `split_points`. A tool that splits there instead is not wrong under lenient scoring (§7). The two labelers' split points are merged, not compared.

Two kinds of `exp` entry are not units; label their parts instead:

- a particle followed by a particle: には, では (で + は), とは, にも, からは;
- a word followed by は, が, を or も, when the sentence uses the plain meaning of the parts: これは, 今日は (きょう + は).

These are the only splits made by form alone, and they apply only to `exp` entries: a particle pair JMdict lists as another part of speech (までに, an adverb) is one unit with a split point. An `exp` entry that ends any other way stays one unit: これまで, このため, ですか, じゃない, として. Interrogative + も (誰も, 何も) is one unit as well, because the sentence uses the entry's own sense ('everyone'; with a negative, 'nobody'), not the plain meaning of the parts; a が after it is a particle (誰も|が). でも (1008460) is one unit only in its own senses ('even' where で marks no case, as in 子供でも; 'but'; 'or something'). Where で keeps a case role (place, means, cause, time), it is で|も: 影の所で|も.

**Conjunctions after a predicate.** A conjunction entry that starts with the copula or ん (だから, ですから, ですが, だが, だけど, なのに, なので, だったら, だって) is one unit only where it opens a sentence or clause. After a predicate or a noun, label the copula and the particle: 天才|だ|から, 明日|な|のに, 忙しくなければ|です|が. After ん, the explanatory entry stays together: んだ|けど, のです|が.

**Quotations.** と言う, って言う and という are one unit only in the linking sense 'called; named; that' (AというB, トムって言う人). A quotation followed by the verb 言う 'say' is と|言う, with the verb's chain: と|言いたい. と思ったら and と考えられている are likewise one unit only in their listed senses.

**Overlaps.** When entries overlap and none covers both, take the analysis that is correct in context. If more than one is correct, take the leftmost-longest entry, the way Yomitan scans: のか|ね, どうしたん|です, うすだいだい|色, 一生一度|だけ. A wrong analysis loses whatever its length: 富士重工業 is 富士|重工業, not 富士重工|業.

An expression that inflects takes a chain like any verb: 気に入らない is one unit with form 気に入る and chain `negative` (spec-09). JMdict tags some inflecting expressions only `exp` (かもしれない), so for those any chain that reaches the form is accepted, except one that strips て + an auxiliary and stops at the te-form, since that auxiliary is a unit of its own: かもしれなかった has chain `-た`. An expression whose ている is contracted keeps its entry, with no chain, and carries `contraction`: in 嘘に決まってる, に決まってる is the expression に決まっている (spec-28). The table would strip the いる and stop at 決まる, the wrong card for 'it's obviously a lie'.

### 4.4 Numbers and counters

A number and its counter are one unit, with a split point between them. A noun is a counter when JMdict tags it `ctr`, or when it is one of these words, which JMdict tags otherwise: 月, 分, 秒, 番, 割, 時, 円, 号, 位, 目, 人, 週間, 時間, か月. After a number written in digits, 万, 億 and 兆 count as counters too where they end the number (50万: entry 万, form 万); inside a number that goes on they are part of it, so 3万8942人 is one unit with the counter 人. Take the longest counter: 3代目 is one unit with the counter 代目. An ordinal 目 after a counter is its own `suffix` unit, unless counter + 目 is itself a counter (代目, 番目): 1隻|目, 2回|目.

Any other noun is a unit of its own after the number: 21|得点, 1|ポイント, 何|世紀, 3|大会. An entry that extends a counter (年ぶり, 日間) isn't used: 19年|ぶり, 7日|間, 1930年|代. After 第, use the 第N entry when JMdict has one (第六|位, 第三|景); otherwise 第 is a prefix (第|41回).

- **When JMdict has the whole span** (一人, 三本, ３回) and one of its senses fits, its entry and spelling are the entry and form: 三本 is entry 1301640, form 三本, reading and form_reading さんぼん (spec-12). In 三歳年上 'three years older', 三歳 is not the entry 'three-year-old' (2872956), so it takes the counter's entry, as below. Nor does a whole-span entry glossed only as a duration fit a clock time: in 3時30分, 30分 takes the counter 分. The validator can't judge senses, so it sends a number + counter that leaves out a whole-span entry to review instead of failing it (`counter-whole-entry`, §8).
- **Otherwise** the entry is the counter's and the form is the counter: 二十本 is entry 1522150 (本), form 本. The reading is the sound-changed reading in context (にじゅっぽん); `form_reading` is the counter's own (ほん) (spec-21).

**Numbers alone.** A number with no counter is one word. Its entry is the whole-span JMdict entry if there is one (17, ４); otherwise it has empty entries and the surface as its form (三十八, 21), and no `oov`. A digit reads as it does in context: ４ read よん has form_reading よん, although JMdict pairs the spelling ４ only with し.

### 4.5 Prefixes and suffixes

A prefix or suffix joins its word only when JMdict has the joined spelling: ご注文 is one entry (spec-17), but お|仲間 is two units (spec-16), and so is 田中|さん (spec-13). A separate prefix or suffix is a `prefix` or `suffix` unit. This holds for suffixes with meaning of their own too (がい, がち, っぽい, ごろ, 方 'way of doing' after a verb stem), and for a bound Sino-Japanese morpheme whose reading in context no entry gives (国 read こく in 連邦国).

A noun right after its host (a word, name, number, or number + counter) that JMdict doesn't join it to is a `suffix` unit as well when JMdict tags the sense used suf or n-suf, or this list names it: 市, 県, 郡, 村, 区, 側, 中, 頃, 姫, 先, 後, 艦, 号, 級, 系, 勢, 星人, 間, 機, 会, 者, 組, 案, 省, 館, 士, 先生, 通り, 夫人, 台, 代, 盤, 当たり, 番地 (サウスノーフォーク|市, 提供|中, 二時|頃, シェーラ|姫, 6|区, 田中|先生). Any other such noun is a word (軍, 役, 市長), and so is a listed one that heads its own phrase (…の後, その側). The `suffix` target goes on the host, a number included.

An unlisted coinage built from listed parts is one `oov` word with split points at its parts (解釈違い, 回線落ち, 寝落ち通話, 景気づける), so tools that split it pass leniently. It is a coinage when it is a set term a learner would look up whole; a free phrase stays parts, and so does a productive verb compound such as stem + 合う (慈しみ|合ってる). A JMdict prefix or suffix still splits off when what remains is a word on its own, listed or not: 激|おこ, クソ|ザコ, 蛙|化, ゆる|勢 (ゆる an `oov` word, form ゆる). A clipped part JMdict lacks keeps the coinage whole (鬼かわ, ぐうかわ, もろバレ), and so does a bare adjective stem: stem + み or さ that the table can't reach is one `oov` word with a split point (しんど·み, エモ·み). A verb coined with る (デバフる, トロる) is one `oov` godan verb with a split point at the noun and its chain as the table reads it.

### 4.6 Names

A name is one unit per JMnedict entry as written, with that entry's id. If JMnedict has no entry for the full name, split it into surname|given name, and only that: two given names, or an invented single name (ラムシャーリー), stay one name. A multi-word surname or a particle + place byname counts as the surname: サシャ|バロン・コーエン, グリエルモ|ダ・モデナ. Invented names with no entry have empty `entries`. Readings are optional and never scored.

A person's name lists every JMnedict entry written as the surface whose type can be a person (surname, given, fem, masc, person, unclass, and mixed types), best guess first; a kana name lists only entries written in kana. Place, company, product and work entries never count for a person: スミス with only a place entry has empty entries. A place, organization or work lists only an entry for that referent; when JMnedict has none, its entries are empty (バーリ, the city of Bari, whose only entry is a surname). ケ and ヶ count as one spelling (鐘ケ坂 takes the entry 鐘ヶ坂); other variants get empty entries (リヤ王 for リア王, VOLVO for ボルボ).

A place, organization or other name that JMdict itself lists (北海道, ニューヨーク, ドイツ空軍) is a `word` with its JMdict id and the `name` target: a learner looks it up like any word. It keeps a separator it is written with (エール・フランス: 5741000, form エールフランス). The `name` target goes only on a unit that is a whole name: a name unit, a word whose entry is the name, or a dictionary word used whole as an individual's name (学園都市 'Academy City'). Dictionary-word parts of a longer name carry only their own targets.

A title, organization, event or facility whose whole name no dictionary lists is labeled by its parts, like any text. Dictionary words are words, a part only JMnedict lists is a name, and a coined part is a name with empty entries: 浅野|木材|工業, 銀河|漂流|バイファム. It is one name unit only when a dictionary lists the whole, or when it is coined whole (Me210).

A proper noun for an individual that no dictionary lists is a `name` with empty entries, never `oov`: a person, place, ship, product or character, or a title, organization, event or facility whose name is coined rather than built from dictionary words (above). A word for a kind of thing (a material, a rank, an office) is a `word`, tagged `oov` when JMdict lacks it (散騎常侍).

### 4.7 Words JMdict lacks

A content word JMdict lacks in the sense used is a `word` with empty `entries`, tagged `oov`: slang, neologisms, technical terms, plain loanwords, fiction terms, sound effects, and a homograph whose JMdict senses don't fit (ロッキング 'locking', where JMdict's ロッキング is 'rocking'). It still needs `form`, `reading` and `form_reading`; if it inflects, give the deinflected form. `oov` never goes on a name (§4.6), an unlisted spelling of a listed word (§5), a fusion (§3), a bare number (§4.4), a form of a listed word the table can't reach (§4.1) or a variant nothing relates (below).

An unlisted noun followed by する is two units: the noun, and する with its chain (煽りプ|されて). A classical verb JMdict lacks is an `oov` word too, with its classical dictionary form (あぐれば: form あぐ, chain `-ば`). A letter + digit designation for a kind of thing (N95, B5, 4K) is one word, `oov` when JMdict lacks it, read as its letters and number are read; one that names an individual is a name.

**Variants nothing relates.** A variant of a listed word that no relation in §5 reaches, such as an old transliteration (ハルレヤ, ステュディオ), a misspelling (ブュッフェ), a dialect pronunciation (よぐ) or a lisp (ショレ for それ), is one `word` with empty entries and the surface as its form, tagged for what it is (`katakana`) and never `oov`.

**Classical forms the table can't reach.** Stop the chain where the table stops. An unreached classical auxiliary with no entry of its own (せる and せし of サ変 verbs, たる, り, き) is an `auxiliary` unit, and a vs noun before it stands alone: 揮毫|せし, 発見|せる. A classical form of a listed word that the table can't reach at all is one word with empty entries: its classical dictionary form if the validator relates it to the surface, else the surface, tagged `archaic-classical`, not `oov` (遠からぬ). Auxiliaries with an entry (べし, ごとし) are words (§3).

**Mimetic + と.** A mimetic followed by と is one unit only when JMdict lists the と form (くるっと). Otherwise the mimetic takes its own entry, or empty entries and `oov`, and と is a particle: パチッ|と, ざわっ|と. An adv-to word with no と entry is the same: 意外|と.

### 4.8 Elongations, variants, kana runs, fragments

- **Stretched spellings.** These keep the entry of the word they stretch. すご〜い is entry 凄い, with form すごい and reading すご〜い (spec-11). 手ぇ is entry 手, form 手, reading てぇ. JMdict lists some stretched spellings as search-only spellings of the entry (すご〜い, すごーい); the gold form is still the standard spelling (§5), and the validator enforces it (`form-orthography`). A stretched inflected form takes its chain: すご〜かった, form すごい, chain `-た`. The validator relates a stretch to its form by their vowel skeleton: ー, 〜 and small vowels are dropped, and so is any vowel that only lengthens the mora before it. So すごおおい, かわいいいい, おいしー, ねえええ and やだぁぁ all keep their entry.
- **Emphatic っ and small vowels.** An emphatic っ or ッ, at the end of a word or inserted inside it, and a small vowel standing for a full one are stretch marks too: 写るーっ is entry 写る with form 写る and reading うつるーっ, ほんっと is ほんと, いっつも is いつも, わぉ is ワオ. Such a unit carries the `elongation` target, which is what lets the validator relate these marks. A lone っ after an ellipsis (了解……っ) is an interjection with no entry.
- **Stretches in chains and after kanji.** A ー that lengthens an -え ending inside a chain stands for that ending: 気をつけねー is one unit, like 気をつけねえ. A full-size vowel after a kanji stretches it, like the ぇ of 手ぇ: 気い is entry 気, form 気, reading きい, form_reading き, and 見いひん is 見る with its Kansai negative chain. An ン inserted in chanted text (なンみンだン) is not a stretch: those units take no entry.
- **Colloquial variants with their own entry.** These take that entry, plus a `normalized` block naming the standard word: すげー is entry 2722660, normalized to すごい / 1374550 (spec-10). Every unit that takes such an entry gets the block, naming the standard word's dictionary form, also when the variant is inflected (わかんない → わかる, つまんない → つまらない, ねえ → ない). Dialect words count (けんど → けれど). This covers dialect and clipped variants with their own entry (ったく → まったく, ちゃうか → じゃないか, ほな → それなら, てめえ → 手前 1328030) and an entry whose gloss defines it as another word's form (なすった → なさる). Where derivation and meaning part, the block names the word with the same meaning. A variant without its own entry, or one §4.1 sends to a chain (やべえ is やばい + `-え`), gets none, and so do a literary form (つまらぬ) and a clipped reading filed under the full word's entry (とこ for 所). Scoring accepts either entry; normalization is scored on its own (§7).
- **Long runs of one kana** (どおおお, ああああ) and repeated laughs (ハハハハハハハ, えへへへへ) are interjections. They take an entry only when the surface is one of its spellings or a stretch of one (§5, `form-relation`); a run longer than every spelling gets empty `entries`, with the surface as the form. A laugh or call that divides into whole copies of a listed spelling whose sense fits is one unit per copy, using the longest such spelling: ハッハッ|ハッハッ, ホホ|ホホ.
- **Repeated mimetics.** A mimetic repeated in whole copies of a listed spelling is one unit per copy: コトコトコトコトコトコト is three units of コトコト. A run that doesn't divide into whole copies is one unit with empty entries and the surface as its form, like a long laugh (ゴシゴシゴシ). Its kind is `interjection` for calls, laughs and cries standing alone (にゃあお) and `word` for adverbial use and sound effects. Such a run of a listed mimetic (ざわざわざわっ, from ざわざわ) carries `onomatopoeia` and never `oov`: the word is listed.
- **Fragments.** A stammered or cut-off fragment followed by the full word is an `interjection` with empty entries, the surface as its form and the `ellipsis-truncation` target: the か of か、甲板, the そ of そ、それ. A cut-off word that isn't repeated keeps its entry, with the full dictionary form and the surface as its reading: 欲し… is entry 欲しい, form 欲しい, reading ほし. A stammer is cut at punctuation, spaces and the full word, never inside an unbroken run: ぼぼ|僕.
- **Function units carry no targets**, and their difficulty is not moved to a neighbour. A stretched particle (わー, よう for よ), a stretched copula (ですー), a contracted particle (っちゃ) or a dialect particle (ねん, さかい) goes untagged. The one exception is `prefix` and `suffix`, which describe the host's boundary and go on the host (§6).

## 5. Fields

| Field | Rule |
|---|---|
| `entries` | The JMdict (or, for names, JMnedict) ids that fit this sense in context, best first. Usually one. Function units have none. A word JMdict has keeps its entry when the surface spells it in a way JMdict lacks (below). |
| `form` | The dictionary form, spelled the way the surface is written. A surface that is itself a spelling of the entry is its own form: 往く stays 往く, 凄い stays 凄い, スゴイ stays スゴイ. Exception: a search-only spelling (すご〜い, すげえ) takes the entry's first standard spelling in the same script: kana for kana, kanji for kanji, katakana for katakana when one exists (すご〜い → すごい, すげえ → すげー). That spelling may add what the surface leaves out, or write a kana part in kanji: お腹すいて → お腹が空く, はね上がる → 跳ね上がる. An inflected surface takes the dictionary form in its own script: たべた → たべる, not 食べる. A katakana surface keeps katakana when JMdict has that spelling, otherwise it takes the hiragana one (ヤった → やる). ASCII stays ASCII: 3つ has form 3つ, which matches JMdict's ３つ. |
| `reading` | How the surface is read in this sentence, in hiragana. Readings are orthographic: は, not わ, and を, not お. A surface made only of kana reads as itself converted to hiragana, ー and 〜 included; ヷ ヸ ヹ ヺ read ゔぁ ゔぃ ゔぇ ゔぉ (ヸオロン: ゔぃおろん). A kanji surface takes its reading in context: 一日 in 四月一日 is ついたち, but in 一日中 the unit is the longer entry (spec-20). Letters read as JMdict reads them, without its ・ (ＣＤ → しーでぃー). When nothing inflects and the surface is the form, `reading` equals `form_reading`, except for rendaku (below). |
| `form_reading` | The reading of `form`, as a JMdict reading of that spelling: たべる for 食べる. This is what a flashcard shows. A digit form takes the reading of its entry that the context uses (§4.4). |
| `chain` | The transform ids from the candidate sheet, dictionary form outward: `["-て", "-しまう", "-た"]`. Empty when the surface is the form. A chain records a path the pinned table accepts from surface to form, and chains are not scored (§7). When the table lacks the right transform, record the path it accepts (くれ as continuative, 見ねえ as negative + `-え`), and don't split the word to dodge it. |
| `split_points` | Offsets inside the unit where its parts are themselves words (§4.3, §4.4). |
| `targets` | The categories this unit stands for (§6). Tag the unit that carries the difficulty, not every unit in the sentence. |
| `normalized` | On every unit that takes a colloquial variant's own entry (§4.8): `{"form", "form_reading", "entries"}` of the standard word. |

**Unlisted spellings.** A spelling JMdict lacks for a word it has keeps that word's entry. The variant may be okurigana, ateji, an old or variant kanji, historical kana, a hiragana spelling of a word JMdict spells only in katakana (りばてぃ), ヴ for バ, Latin letters for a loanword JMdict spells in katakana (BUS for バス), or a particle dropped from a phrase entry. `form` is the entry's first standard spelling as JMdict lists it, in the surface's script where one exists (当てがった: 宛がう, not 宛てがう), and of those the first the reading relates to (カンヴァス: カンバス, not キャンバス); an entry with no standard spelling in that script takes its kana one (不可ない: いけない, whose 行けない is search-only); `reading` is the reading in context; `chain` is as usual. Tag the unit `kanji-variant` (`archaic-classical` for historical kana), never `oov`; that target is what lets the validator relate surface and form through the reading. A katakana spelling of a word JMdict spells in hiragana or kanji (ヤった for やる) is already related as kana vs katakana: tag it `katakana-form`, not `kanji-variant`. A phrase entry stays one unit. So 塗みれた is entry 塗れる, form 塗れる, reading まみれた, form_reading まみれる, chain `-た`; 寝ころがって is 寝転がる; ヴォイド is ボイド; どーゆう is どういう; 云うに云われぬ is one unit with the entry of 言うに言われぬ; 腹減って is entry 腹が減る, form 腹が減る, reading はらへって, form_reading はらがへる, chain `-て`.

A surface that relates to a listed spelling as a stretch takes that spelling as its form (ヘヴィー: ヘヴィ), as ナア――ンダ takes なあんだ; the first-standard-spelling rule applies only when nothing relates it so.

**Readings JMdict doesn't list.** `reading` is the reading in context even when JMdict doesn't give it for the spelling. Rendaku in a part of a split compound is fine: in 灯明|皿, 皿 reads ざら, with form_reading さら. A reading that makes the spelling another listed word (妾 read あたし) is an unlisted spelling of that word. A reading no word has (真名 read しんめい) means empty entries and `oov`.

**Free variants.** Readings follow the spelling: 言う reads いう even in Kansai speech, unless the surface writes ゆう. A number + counter takes the sound change of spec-21, with じゅっ before a voiceless counter (30歳 is さんじゅっさい). Otherwise, where a spelling's readings vary freely, take the first reading JMdict marks common, or the first it lists when none is (私達 わたしたち, ＯＫ おっけー); `jmdict lookup` lists readings in JMdict's order and stars the common ones. Only something in the text fixes a free variant's reading: furigana, a kana spelling, a pun or meter. Register, domain and naturalness don't, so その後 reads そのあと in formal prose and 内側 うちがわ in an anatomy text. A reading tied to a sense of its own is a heteronym, chosen by sense (§6).

**Records without context.** A record too short to settle a reading, such as a lone word from a tool's test suite, takes the most frequent reading. Ruby the source had but the record's text lacks doesn't count: the reading is the one a reader of the text gets (他 read た, not the author's ひと).

## 6. Categories

Each category names one kind of difficulty, and a unit's `targets` list the ones it stands for. `src/monosashi/taxonomy.py` holds the same definitions, and the validator checks `targets` against it. Tag each unit from these definitions. The tagger's hints on the candidate sheet are only suggestions: drop a wrong one, and add a category no hint names when a unit stands for it. The two labelers' targets are compared like every other field.

### Unit boundaries

- `compound`: A compound or lexical phrase that is one JMdict entry (一人暮らし, 気に入る, どうでもいい).
- `grammar-expression`: An expression of function words, the copula or auxiliaries that is one JMdict entry (かもしれない, ですか, んです).
- `inflection-chain`: A verb or adjective with two or more transforms in its chain (食べさせられなかった).
- `te-auxiliary`: A chain through て + いる/しまう/おく/みる/くる/いく/ある/あげる/くれる/もらう/ほしい, contracted or not (始めてしまった, 食べちゃった, 見せてもらった).
- `contraction`: A colloquial contraction, inside a chain or as its own entry (ちゃう, てる, なきゃ, ねえ, わかんない, こりゃ).
- `suru-verb`: A noun + する unit mapped to the noun's entry (勉強している).
- `counter`: A number + counter unit (三本, 二人, 5回).
- `prefix`: A word with a prefix, joined by its entry or as a separate unit; tagged on the word (ご注文, お|仲間).
- `suffix`: A word with a suffix, joined by its entry or as a separate unit; tagged on the word (田中|さん, 学生|たち).
- `long-compound`: A kanji run of four or more characters that is not one entry, tagged on each of its content units (選挙管理委員会).
- `katakana`: A katakana loanword or run, including runs that tempt a mis-split (アイス|ベア).
- `name`: A proper name of an individual: a person, place, organization, work or product.
- `kana-written`: A word usually written in kanji, written in kana (きれい, すごい, わかる); not where kana is standard.

### Forms

- `jiru-zuru`: An inflected じる/ずる verb, whichever headword its surface forces (感じた -> 感じる, 感ぜられ -> 感ずる).
- `archaic-classical`: A classical or archaic form, including historical kana (美しき, せねば, ざる).
- `potential-ranuki`: A chain with a potential transform, ra-nuki or not (見れる, 来れる, 書ける, 食べられる).
- `kanji-variant`: A spelling JMdict lacks, or marks irregular, outdated or search-only, for a word it lists (塗みれた, 寝ころがる, ヴォイド).
- `colloquial-variant`: A variant with its own entry and a normalized block naming the standard word (すげー -> すごい).
- `elongation`: A visibly stretched surface: a long vowel, 〜, an added small kana or an emphatic っ (すご〜い, 手ぇ, ほんっと).
- `kana-run`: A run of repeated kana or an interjection made of one (どおおお, あああ).
- `katakana-form`: A word normally written in hiragana or kanji, written in katakana (ヤル, ワタシ, スゴイ).

### Readings

- `heteronym`: A spelling with readings in common use that belong to different words or senses, picked by context (一日, 何, 方); not free variants (行く いく/ゆく).
- `counter-reading`: Any reading change where a number meets a counter or another kanji (三本 さんぼん, １４人 じゅうよにん, 一切 いっさい).
- `kinship`: A kinship or address term written with kanji whose kanji take a reading they have only in such terms (お兄ちゃん おにいちゃん).

### Robustness

- `kansai`: Kansai-ben forms (へん, やん, あかん, ちゃう, おおきに).
- `ellipsis-truncation`: A word actually cut off by an ellipsis or a stammer (欲し…, あ、あの); not a whole word that trails off.
- `onomatopoeia`: A mimetic or sound-symbolic word (ドキドキ, ふわふわ).
- `oov`: A content word JMdict lacks in the sense used (slang, a technical term, a loanword); never a name or an unlisted spelling.

### Where the tags go

- Function units carry no targets (§4.8). `prefix` and `suffix` go on the content unit the affix attaches to: the next unit for a prefix, the previous one for a suffix (仲間 in お|仲間, 田中 in 田中|さん).
- `long-compound` goes on every content unit with a kanji in the run it names, the maximal string of kanji (ガチャ禁三日目: ガチャ禁 and 三日), names and kanji numerals included. A number in digits (with 万, 億 and 兆 after digits) is not part of a run, so 10万人以上 holds none.
- `grammar-expression` goes on a unit that is one entry made of two or more words, none of them a content word in its own sense: particles, the copula, auxiliaries, ん or の, and する, なる, いう or 思う used as grammar (かもしれない, ですか, んです, のように, かどうか, までに, として, とする, となる, ちゃいけない). It also goes on ならない and いけない 'must' after a conditional, と or ては, and on 違いない after に. A lexical phrase is a `compound` (気に入る, どうでもいい, うまくいく, わけのわからない, 御覧なさい). One word with its own inflection (構わない, そうだ, ようだ, ように, みたいだ, ください, だろう) or one content word plus a particle (急いで, ために, それから) is neither, `exp` or not: it carries only the targets another definition gives it.
- `compound` goes on a content unit that is one entry whose parts are words, so it has split points (一人·暮らし, 見·渡す, 島·国, この·ほう). Not on a grammar expression, a number + counter, or one word with its inflection or a particle (何時か, 実際に, 心から, 同様に); a word whose parts aren't words (勉強) gets none.
- `contraction` covers a colloquial contraction however JMdict files it: an entry of its own (わかんない), a spelling of the standard entry (とこ for ところ, もん) or a chain. An -え ending (ない → ねえ, たい → てえ, い → え) is a `contraction`, like ちゃう and てる, wherever it appears: inside a chain (やべえ) or in a unit with its own entry (すげー). So is any other contraction with its own entry (わからん, わかんない, じゃない for ではない). `colloquial-variant` goes only on a unit with a `normalized` block.
- `potential-ranuki` goes on every chain with a potential transform (`potential`, or `potential or passive` read as potential), ra-nuki or not; the name is kept from earlier versions. A godan passive read as potential counts (待たれへん). A derived verb with an entry of its own (思える, 切れる) has no such transform and carries no tag.
- `elongation` goes on any surface that visibly stretches, even when JMdict lists the stretched spelling (えー, あのー), but not on a kana run with no base word: どおおおおっ is `kana-run` only. A small vowel that spells a contracted ending (てめぇ, 切ねぇ) is no stretch: such a unit carries `contraction` only.
- `kana-run` goes on a unit of one kana stretched or repeated (どおおお, ああああ) and on every run §4.8 leaves undivided with empty entries, whether of a kana, a syllable or a mimetic (ハハハハハハハ, ごろごろごろ, パチパチパチッ). Whole copies of a listed spelling don't carry it.
- `kanji-variant` goes on a spelling JMdict lacks, or tags irregular (iK, ik, io), outdated (oK, ok) or search-only (sK, sk); `jmdict lookup` shows the tags. Rare (rK) and ateji spellings and untagged secondary spellings get none (泊る, 瘠せる).
- `archaic-classical` goes on forms JMdict marks arch or obs and on classical inflections (美しき, せねば, ざる), not on formal words in modern use (うる, たまえ).
- `kana-written` does not go where kana is the standard spelling (さいたま), and `katakana-form` does not go on words normally written in katakana (ヒヒ). JMdict's 'usually kana' tag doesn't settle kana-written: it goes on a kana surface whose entry has a kanji spelling JMdict marks common, so わかる, すごい, よい, かわいい, ほめる and このあいだ count, while そう, あの and これ, rarely written in kanji, don't, nor does がんとして.
- `heteronym` needs two readings in common use that belong to different words or senses: 方 (かた, ほう), 一日, 何, and kanji-written particles such as 位 (くらい, い). A reading counts as in common use when JMdict marks it common or the sentence uses it. So 来る read くる is not a heteronym because of きたる, nor 学生 because of the archaic がくしょう. A reading counts only when its entry can fill the unit's role: for a free noun, readings JMdict gives only as a prefix or suffix don't count (店 みせ, not てん), and for an affix unit free-noun readings don't. Free variants of one word are not heteronyms (行く いく/ゆく, 言う いう/ゆう), nor is a register variant that JMdict files as an entry of its own (私 わたし/あたし, あたし marked feminine). `kinship` goes only on surfaces with kanji. `counter-reading` covers the numeral's own change (１４人 じゅうよにん, 3つ みっつ) and compounds that are not counters (一切). A longer entry carries `heteronym` or `counter-reading` when a part between its split points would (一日·中, 一人·暮らし ひとりぐらし), because a tool that splits it there still has to read that part.
- `counter` means a number + counter that counts or orders something: 一切, 一通り 'ordinary' and 一部 'some of' carry none, though 一通り keeps `counter-reading`.
- `kinship` goes on 兄 read にい, 姉 ねえ, 父 とう, 母 かあ, 爺 じい, 婆 ばあ and the like (お兄さん, お爺さん), not where the kanji keep ordinary readings (奥さん, 娘さん).
- `jiru-zuru` goes on every inflected unit whose verb is one of a じる/ずる pair (感じた → 感じる, 感ぜられ → 感ずる); a surface in its own dictionary form (生ずる) gets none.
- `ellipsis-truncation` needs a word actually cut off (欲し…) or stammered (あ、あの); a complete word that trails off (待って…) does not count.
- `oov` covers slang, technical terms, plain loanwords, fiction terms, sound effects and homographs whose JMdict senses don't fit (§4.7). It never goes on names (§4.6), unlisted spellings (§5), fusions (§3) or bare numbers (§4.4).
- `kansai` goes on a unit whose entry JMdict marks ksb in the sense used (わい 'I', ちゃうか, やんか), on a unit whose same-span entry has a fitting ksb sense (ええ 'good', labeled いい + `-え`), and on a chain with a Kansai transform; nothing else (めっちゃ, 帰ろ). The senses and `jmdict lookup` show ksb with the other tags.
- No dialect category exists besides `kansai`: an Iyo or Edo form gets only the tags for what it is (`contraction`, `archaic-classical`).
- A chain recorded only as the table's path to the form (§5 `chain`) adds no target of its own: Kansai 買うてん 'bought' is `inflection-chain`, `kansai` and `contraction`, not `te-auxiliary`.

## 7. How labels are scored

Scoring rules do not change what a label means, so changing one does not invalidate records. The scorer implements this section.

A tool's output for a record is a list of units with `start`, `end` and `surface`, and optionally `form`, `reading`, `form_reading`, `entries` and `kind`. A tool is scored only on the fields it outputs. Predicted units that cover only symbols are dropped first. Readings are compared in hiragana.

**Content units.** A gold unit is content when its kind is word, expression, name or interjection. A predicted unit is content unless its `kind` is a function kind. For a tool that outputs no kinds, every unit of a content-only tool is content (each one is a card it offers), and a unit of a tool that covers the whole sentence is content unless its span is exactly a gold function unit. Only a predicted content unit can earn a card: a unit the tool itself marks as a particle or auxiliary earns none, even when its span and form match.

**Accepted forms.** A tool's form is accepted when it is any JMdict spelling of the gold unit's entries or of its `normalized` entries, compared after widening ASCII. A noun + する unit also accepts the noun with する (勉強 or 勉強する). Search-only, outdated and rare spellings count: a tool that keeps the surface spelling (すご〜い) or prints the standard kanji (凄い) is not wrong. The gold `form` is stricter (§5) only so that two labelers write the same thing. A `form_reading` is accepted when it is the gold one or the one that goes with the tool's form: the normalized `form_reading` with a spelling of a normalized entry (すごい, すごい for すげー), and the gold `form_reading` + する with the noun + する form (勉強する, べんきょうする). The form and the `form_reading` must also belong together, as a spelling and a reading of one accepted entry (the する form counts as the noun's spelling): 凄い paired with a reading that only another gold entry has fails. For a unit whose form is the counter (§4.4), an accepted form and `form_reading` are not enough: the tool's `reading` must also be the gold `reading`, the sound-changed reading in context (にじゅっぽん for 二十本), so the counter with only its own reading (本, ほん) fails.

**Other ways to pass.** Some gold units can also be passed in these ways:

- **No entry.** A gold unit with no entries has no dictionary form to check. It passes on its span and its reading in context, whatever the tool's form: the tool's `reading` must be the gold `reading`. When the tool outputs no `reading`, a gold unit with no chain compares the tool's `form_reading` with the gold `reading`, and one with a chain passes when the tool's form and `form_reading` are the gold `form` and `form_reading` (ググった: ググる, ぐぐる).
- **Number + counter.** For a unit whose form is the counter (§4.4), a tool may also give the whole surface as its form (二十本, compared after widening ASCII), with the gold `reading` as its `reading` or, when it outputs none, as its `form_reading`.
- **Noun + する.** A tool that offers the noun alone passes on the noun's span: 勉強 (form 勉強, form_reading べんきょう) for 勉強した. This holds in strict and lenient scoring; the rest of the unit (した) is not junk, and the unit stays in the lenient count.
- **Derived verbs.** A unit whose entry is a verb derived by a voice transform also accepts the base verb, and a unit whose chain starts with a voice transform (potential, passive, causative) also accepts the derived verb: 思える accepts 思う (おもう), and 行う with chain `passive` accepts 行われる (おこなわれる). The judgment call of §4.1 then doesn't move scores. Each alternative counts as a pair: the other verb's spelling with that verb's reading. A chain starting with -すぎる or -がる likewise accepts the entry it passes through (多すぎる, 恥ずかしがる).

**Card-ready rate, the headline.** Of the gold content units that are neither names nor interjections with no entry (laughs, calls, shouts and stammered fragments, §4.8), the share for which the tool outputs a content unit with the same span, an accepted form, and an accepted `form_reading` (and, for a unit whose form is the counter, the gold `reading`), or passes in one of the ways above. Entry ids play no part, so a tool that outputs ids has no second way to pass. Grammar expressions count (§11 Q2). It is reported two ways:

- **strict:** as above;
- **lenient:** a gold unit the tool cuts only at its `split_points` (一人|暮らし for 一人·暮らし), and that does not pass otherwise, is left out of the count instead of failing.

**Junk rate**, always shown next to the card-ready rate: the share of the tool's content units that match no gold content unit. A unit matches when its span is a gold content unit's, or when it is a piece of an accepted split of one; the noun and the rest of a noun + する unit count as such pieces. Without it, a tool could raise its card-ready rate by emitting more words.

**Segmentation**, for tools that output a full partition:

- **Strict:** precision, recall and F1 of unit spans against gold unit spans.
- **Lenient:** F1 over unit boundaries, with every gold `split_points` offset removed from both sides, so splitting there is neither rewarded nor penalized.
- **Content-unit F1:** content units only, by span. It is the only segmentation score for tools that output content units alone.

**Form, reading and form_reading accuracy**, each with its coverage, measured two ways:

- **exact:** on gold units the tool reproduces span for span;
- **tiled:** on gold units the tool's pieces cover exactly. The reading is the pieces' readings joined, and the form is the first content piece's form.

Tiling keeps the comparison fair to tools that split every chain: without it, their readings would be measured only on the units they happen to segment like gold.

**Entry accuracy**, for tools that output JMdict ids: a unit is right when the tool's first id is one of the gold entries or normalized entries. An id that is not in the pinned snapshot goes to a separate version-mismatch count instead of counting as wrong. Name ids are compared against JMnedict.

**Normalization accuracy**, on units with a `normalized` block: the tool's form is a spelling of a normalized entry, or its first id is one.

**Names and interjections with no entry** count toward segmentation and junk; name readings are never scored.

**Slices.** Every record belongs to one slice:

- `open`: sentences from the open corpora (Tatoeba, Aozora Bunko, UD Japanese GSD);
- `plain`: open-corpus sentences drawn at random from those the tagger flags nothing in, a baseline for ordinary text;
- `seed`: sentences from the tools' own test suites;
- `synthetic`: lines Claude wrote for categories that real text covers thinly.

**Breakdowns.** Each tool gets one overall row, computed on every record except seeds, since a tool's own test sentences can't judge it fairly; open, plain and synthetic records all count. Seeds get a table of their own, by test suite. Then come marginal tables by category (scored on the units whose `targets` name it), by register and by slice. The category and slice tables include seeds. The register table leaves them out, since a seed's register is its test suite's rather than its text's, and states each register's source and slice composition, because outside the seeds the casual registers draw on few sources. Overall rows and comparisons between the top tools carry 95% intervals from a paired bootstrap that resamples records. A record a tool crashes on or garbles scores as if the tool had output nothing.

**Cost:** median milliseconds per sentence, warm. It is timed inside each adapter, so it includes the adapter's own overhead, such as ichiran's container round trip.

## 8. Validation

`monosashi validate FILE…` reports each issue with a rule id. A labeler fixes every issue before handing in.

| Rule | Checks |
|---|---|
| `schema` | the line is valid JSON with exactly the documented fields and types |
| `text-empty`, `text-normalized` | text is non-empty and already normalized (§2) |
| `span-bounds`, `span-surface`, `span-order`, `span-symbol` | spans fit the text, match their surface, do not overlap, and do not start or end on a symbol |
| `span-inner-symbol` | a space or symbol inside a unit is one §1 allows: a line-break space, a digit-group comma, a ― between kana, ／＼, or a name separator (・ = ＝ - － or a space) in a name unit or a word tagged `name` |
| `coverage` | every non-symbol character belongs to a unit |
| `kind`, `kind-expression` | the kind exists; the exp rule of §3 |
| `function-entries`, `function-normalized`, `function-targets` | function units carry no ids, no normalized block and no targets |
| `content-fields` | word, expression and interjection units have `form`, `reading`, `form_reading` |
| `reading-kana`, `reading-kana-surface`, `reading-form-reading` | readings are hiragana; a kana-only surface reads as itself; with no chain and surface = form, reading = form_reading, except a voiced first kana right after another content unit (rendaku, §5) |
| `form-orthography` | the form is the one the surface reaches as written (§5): its own spelling, the standard spelling for a search-only one, in the surface's script, and for an unlisted spelling the one §5 names; a kana surface has a kana form |
| `form-search-only` | when the surface fixes no form, the form is still not a search-only spelling if the entry has a standard one |
| `entries-exist`, `entries-duplicate` | ids exist in the pinned snapshot (JMnedict for names) and appear once |
| `form-spelling`, `form-reading` | the form is a spelling of an entry; `form_reading` is a reading of that spelling, or any reading of the entry for a digit form (§4.4) |
| `chain-ids`, `chain-deinflects`, `chain-missing`, `chain-maximal` | chain ids exist; the chain turns surface into form for the entry's POS (for a unit tagged `kanji-variant` or `archaic-classical`, it may turn reading into form_reading instead); an inflected unit records its chain; the unit does not stop before a following unit it could absorb (a chain's tail, or the する after a vs noun), unless that unit is a sentence-final よ, ね, ねえ or ねぇ it would reach only through a contracted -いる or -おく (§4.1) |
| `form-relation` | with no chain, something relates surface and form: the same spelling, kana vs katakana, a stretch (same vowel skeleton, §4.8), a number + counter (§4.4), or, for a unit tagged `kanji-variant` or `archaic-classical`, its reading, also with a particle the phrase spells dropped (§5) |
| `split-points`, `targets` | split points fall inside the unit, ascending; categories exist |
| `normalized-*` | the normalized block names a real entry, spelling and reading |
| `register`, `slice`, `label-status`, `label-spec`, `license`, `id-duplicate` | record fields are known values; the source license is on the allowlist; ids are unique |

Before every dictionary check, the validator strips the inner symbols §1 allows: a ― between kana reads as ー, ／＼ repeats the two kana before it, an iteration mark repeats the kana before it, and a word tagged `name` drops its separators. An emphatic っ, and a small vowel standing for a full one (わぉ for ワオ), relate as stretch marks only on units tagged `elongation` (§4.8).

Advisories are printed with their rule id but do not fail validation; the review queue picks them up.

| Advisory | Flags |
|---|---|
| `counter-whole-entry` | a number + counter that JMdict lists whole, labeled without that entry; the reviewer checks whether one of the entry's senses fits (§4.4) |

## 9. Worked examples

Each example is a record in `tests/fixtures/spec-examples.jsonl`, and the test suite validates them all, so the examples cannot drift from the rules. `|` marks unit boundaries; `·` marks split points.

| id | Units | Shows |
|---|---|---|
| spec-01 | 彼女\|は\|一人·暮らし\|を\|始めてしまった | compound with a split; chain `-て, -しまう, -た` |
| spec-02 | 食べちゃった | contraction inside the chain: `-ちゃう, -た` |
| spec-03 | 食べてみた | the `-みる` supplement: `-て, -みる, -た` |
| spec-04 | 行かなければ\|ならない | the chain wins over なければならない; ならない is the expression 'must' (2083990) |
| spec-05 | 勉強している | noun + する; form 勉強 |
| spec-06 | 学生\|じゃ·ない | an expression after a noun is its own unit |
| spec-07 | そう\|です·か | grammar expression ですか, split accepted |
| spec-08 | 来る\|かも·しれない | the longest entry over its parts |
| spec-09 | 気·に·入らない | an inflecting expression takes a chain: form 気に入る, `negative` |
| spec-10 | すげー | its own entry (exp + int, so an interjection), normalized to すごい |
| spec-11 | すご〜い | stretched: entry 凄い, form すごい, reading すご〜い |
| spec-12 | 三·本 | counter with its own entry (1301640): form 三本 |
| spec-13 | 田中\|さん | name with every JMnedict person entry for 田中 (5543705 to 5543714, best guess first) and a suffix; the `suffix` target goes on 田中 |
| spec-14 | あの\|方 | 方 read かた (1516925) |
| spec-15 | こっち\|の\|方 | 方 read ほう (1516930) |
| spec-16 | お\|仲間 | prefix JMdict does not join |
| spec-17 | ご·注文 | prefix JMdict does join |
| spec-18 | 感じた | form 感じる, not the archaic 感ずる |
| spec-19 | 見れる | ra-nuki potential: `potential` |
| spec-20 | 一日·中 | 一日 inside a longer entry |
| spec-21 | 二十·本 | counter with no entry of its own: form 本, reading にじゅっぽん, form_reading ほん |
| spec-22 | 3つ | ASCII stays ASCII; the form 3つ matches JMdict's ３つ |
| spec-23 | 見せてもらった | the `-もらう` supplement: `-て, -もらう, -た` |
| spec-24 | 出てった | contracted ていった, inside the chain: form 出る, `-て, -いく` |
| spec-25 | ほんっと | an emphatic っ is a stretch mark: entry 1523060, form ほんと, reading ほんっと, target `elongation` |
| spec-26 | 買って\|よ | a sentence-final よ stays out of the chain, though てよ could read as a contracted ている |
| spec-27 | 見\|ながら | a one-kanji ichidan stem reaches its verb: entry 1259290, form 見る, reading み, chain `continuative (kanji stem)` |
| spec-28 | 嘘\|に·決まってる | an expression whose ている is contracted keeps its entry: 2841446, form に決まっている, reading にきまってる, no chain, `contraction` |

## 10. Design notes

These came out of building the validator against the real snapshot.

- **Scoring accepts every spelling; the gold form is stricter.** JMdict tags real surface spellings search-only, such as すげえ and すご〜い, so rejecting them in scoring would fail tools that keep the surface spelling. Scoring therefore accepts any spelling of the entry (§7). The gold form follows §5: the surface's own spelling, or the standard one for a search-only spelling. A search-only kana spelling is never accepted as a reading of the entry's kanji forms.
- **〜 U+301C, not ～ U+FF5E**, is the one tilde, because JMdict spells with 〜.
- **Chains use Yomitan transform ids** (`-て`, `-しまう`, `-た`, `potential or passive`), not bare kana, so the validator can check them. The supplements of §4.1 use ids in the same style.
- **Name ids refer to JMnedict**, because the two dictionaries share id ranges.
- **`expression` vs `word`** is decided by JMdict's exp tag (§3).

## 11. Settled questions

The owner settled these on 2026-10-15, each at its proposed default. Reopening one changes the spec and bumps its version.

- **Q1. Other て + auxiliary verbs.** Reopened on 2026-10-17 and reversed in 0.3: て + くる / いく / ある / あげる / くれる / もらう / ほしい are inside the chain, like いる / しまう / おく / みる, through supplements (§4.1). The 0.2 default had made them separate units only because the pinned table has no transform for them.
- **Q2. Grammar expressions as cards.** ですか, じゃない and かもしれない are `expression` units and count toward the card-ready rate, since learners look them up (§7).
- **Q3. The form of a counter with no entry of its own.** It is the counter: 二十本 has form 本. The whole surface would be a form no JMdict spelling can validate. Counters JMdict lists whole (三本, ３回) take the whole span when one of the entry's senses fits (§4.4).
- **Q4. Full names.** Split surname|given name unless JMnedict has the full name (§4.6).
- **Q5. Kana-surface readings.** Keep ー and 〜 exactly as written (すご〜い), so a reading always spells the surface (§5).

## Changelog

- 0.1 (2026-10-15): first draft. Open questions Q1–Q5 settled at their defaults, which changed no rule. §7 now holds the full scoring definitions.
- 0.2 (2026-10-16), clarified during labeling: §3 states which exp entries may be words, as the validator checks; function units carry no targets (`function-targets`); heteronym and counter-reading targets are compared, the rest merged. Rulings from the 50-record pilot (unit agreement 93.8%, record agreement 70%, counted before split points stopped being compared; 96.3% and 82% after). An `exp` entry beats a same-span chain; a non-`exp` entry loses to it (§4.1). Particle pairs and word + は/が/を/も `exp` entries are split (§4.3). 万/億/兆 after digits count as counters; ordinal 目 is a suffix (§4.4). Meaningful suffixes and bound morphemes stay suffix/prefix units (§4.5). Names JMdict lists are words with the `name` target; titles and products are names (§4.6). Unlisted noun + する and classical verbs (§4.7). Kana runs and stretched particles (§4.8). The な after a na-adjective is a copula (§3). Split points are merged, not compared. Where `long-compound` and `ellipsis-truncation` go (§6).
- 0.2, scoring (2026-10-16): §7 rules made while building the scorer; scoring rules change no label, so records keep their version. Every unit of a content-only tool that outputs no kinds is content, a card it offers. A noun + する unit also accepts the noun with する as its form (勉強する). Besides the gold `form_reading`, the one that goes with the tool's form is accepted: the normalized reading with a normalized spelling, the gold reading + する with the する form; card-ready uses the same rule. Register tables leave out seeds.
- 0.3 (2026-10-17), the owner's rulings on the labelers' questions from the first core run. §12 is removed: the spec says what a label means and how it is scored, and nothing more. A unit may contain the spaces and symbols that split one word (§1). Auxiliaries with an entry of their own are words; に and で after a na-adjective, and conditional and polite copula forms, are copula units; kana particles with another part of speech stay particles, kanji-written ones are words; word + particle fusions; interjection vs expression is no disagreement (§3). An entry wins only when one of its senses fits (§4). て + くる / いく / ある / あげる / くれる / もらう / ほしい join the chain, with supplements for them and for Kansai る → ん, the Kansai adjective negative, the short volitional and -ゃがる (Q1 reversed). Where the table stops; a sentence-final よ or ね stays out of the chain; ならない after a conditional is the expression 'must' (spec-04 changed); an expression containing a whole chain is one unit; nouns, adnominals and derived verbs keep their entry when it fits (§4.1). Noun + する edge cases (§4.2). Conjunction entries after a predicate, quotative と言う, the overlap tie-break, 誰も and 何も (§4.3). Counters are JMdict `ctr` nouns plus a fixed list; a whole-span counter entry needs a fitting sense, and `counter-whole-entry` becomes an advisory; numbers without a counter (§4.4). Nouns bound to a host are suffixes; coinages from listed parts (§4.5). Which JMnedict ids a name takes; titles and organizations are labeled by their parts; individuals are names and kinds are words (§4.6). What `oov` covers; classical forms the table can't reach; mimetic + と (§4.7). Emphatic っ and small vowels as stretch marks, stretches in chains and after kanji, `normalized` on every own-entry variant, repeated mimetics, fragments, function units untagged (§4.8). Unlisted spellings keep their entry, readings JMdict doesn't list, free variants, records without context, chains as accepted paths, search-only forms (§5). §6 defines every category; prefix and suffix targets go on the host; heteronym, counter-reading, kinship, contraction, grammar-expression, potential-ranuki, elongation, kana-written, katakana-form and oov are redefined; all targets are compared, and the tagger's hints are suggestions. §8 adds `span-inner-symbol`. The worked examples' targets follow the §6 definitions; spec-13 now tags 田中 `suffix`.
- 0.3, scoring (2026-10-17): form and form_reading must be a pair from one accepted entry; units with no entry pass on span and reading in context, or for a tool with no reading on the form and form_reading; a number + counter needs the sound-changed reading; the noun alone passes for a noun + する unit; only units a tool offers as content earn cards; fragments are left out of card-ready, like names; the base or derived verb is accepted for derived-verb and voice-chain units. Overall rows leave out seeds, which get their own table by suite; the new `plain` slice counts in them. The register table states each register's source and slice composition. Cost is timed inside each adapter, overhead included.
- 0.4 (2026-10-17), the owner's rulings on the 50-record pilot's questions. One-kanji ichidan stems reach their verb through `continuative (kanji stem)` (見ながら, spec-27). An adnominal entry that is only a verb's past or negative is that verb with its chain (残った, §4.1). Only `exp` particle pairs split (までに stays whole), and an expression whose ている is contracted keeps its entry (に決まってる, spec-28; §4.3). A run of a listed mimetic is never `oov` (§4.8). Free variants take the first common reading, and an unlisted spelling's form is the entry's first standard spelling, which the validator enforces (§5). One-word `exp` entries are neither `compound` nor `grammar-expression` (§6).
- 0.4, scoring (2026-10-17): interjections with no entry (laughs, calls, shouts, stammered fragments) leave the card-ready rate, like names.
- 0.5 (2026-10-17), rulings on the questions labelers raised in the 994-record core run (unit agreement 93.6%, record agreement 68.1%). Validator fixes: a particle dropped from a phrase entry relates through the reading (腹減って); an unlisted spelling's form is the first standard spelling its reading relates to, or the kana one when the script has none (カンヴァス, 不可ない); ヷヸヹヺ read ゔぁ..ゔぉ; iteration marks ゝゞヽヾ are spelled out; a word tagged `name` may hold a separator (エール・フランス). `-いく` covers ゆく. Kanbun is out of scope (§1). The copula's past and polite forms (だった, でした, じゃった) are copula units, and に/で are the copula only after an adj-na word (§3). A particle alone is an interjection; word vs interjection on an int entry is no disagreement (§3). いけない and 違いない as grammar after a conditional or に; ざるを得ない after a chain; a godan/vs-s tie takes the godan form; adverb entries with senses the adjective lacks (§4.1). せざるをえない splits off a vs noun; vs-s entries beat noun + する (§4.2). でも vs で\|も; 誰も\|が (§4.3). 万 inside a number; durations in clock times (§4.4). Which bound nouns are suffixes; coinages, stems + み, coined る verbs (§4.5). Which JMnedict entries a person's name lists; multi-word surnames; where `name` goes (§4.6). Variants nothing relates have empty entries; letter + digit designations (§4.7). Which variants get a normalized block; laughs in whole copies; stammers (§4.8). Latin spellings; stretches of a listed spelling; register doesn't pick a free variant's reading; lost ruby doesn't count (§5). `grammar-expression`, `compound`, `contraction`, `long-compound`, `kana-run`, `kanji-variant`, `archaic-classical`, `kana-written`, `heteronym`, `counter`, `kinship`, `jiru-zuru`, `potential-ranuki` and `kansai` made precise, and JMdict's dialect tags shown (§6). spec-13 lists every person entry for 田中.
- 0.5, scoring (2026-10-17): a chain starting with -すぎる or -がる also accepts the entry it passes through (多すぎる).
