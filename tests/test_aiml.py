import time

from harness.aiml import Bot, normalize


def bot(body, **kw):
    return Bot([f"<aiml>{body}</aiml>"], **kw)


def say(b, text, **pred):
    return b.respond(text, pred)[0]


def test_normalize():
    assert normalize("Hello, World! ledger_entries 2026.09.4") == "HELLO WORLD LEDGER ENTRIES 2026 09 4"


def test_exact_and_wildcards():
    b = bot(
        "<category><pattern>HELLO</pattern><template>hi</template></category>"
        "<category><pattern>HELLO *</pattern><template>hi <star/></template></category>"
        "<category><pattern># MONDAY #</pattern><template>monday</template></category>"
        "<category><pattern>*</pattern><template>fallback</template></category>"
    )
    assert say(b, "hello") == "hi"
    assert say(b, "Hello there Priya") == "hi there priya"
    assert say(b, "moved to monday") == "monday"
    assert say(b, "Monday") == "monday"
    assert say(b, "nothing relevant") == "fallback"


def test_priority_order():
    b = bot(
        "<category><pattern>_ X</pattern><template>underscore</template></category>"
        "<category><pattern>A X</pattern><template>word</template></category>"
        "<category><pattern>* X</pattern><template>star</template></category>"
    )
    assert say(b, "a x") == "underscore"
    b = bot(
        "<category><pattern>A X</pattern><template>word</template></category>"
        "<category><pattern>* X</pattern><template>star</template></category>"
    )
    assert say(b, "a x") == "word"
    assert say(b, "b x") == "star"


def test_no_match_is_silence():
    b = bot("<category><pattern>HELLO</pattern><template>hi</template></category>")
    assert say(b, "goodbye") == ""


def test_that_and_topic():
    b = bot(
        "<category><pattern>WHEN</pattern><template>which table</template></category>"
        "<category><pattern>*</pattern><that>WHICH TABLE</that><template>got it: <star/></template></category>"
        "<category><pattern>*</pattern><template>?</template></category>"
        "<topic name='BILLING'><category><pattern>*</pattern><template>billing <star/></template></category></topic>"
    )
    assert say(b, "when") == "which table"
    assert say(b, "ledger") == "got it: ledger"
    assert say(b, "ledger") == "?"
    b.predicates["topic"] = "billing"
    assert say(b, "invoice") == "billing invoice"


def test_srai_set_get_condition():
    b = bot(
        "<category><pattern>HI *</pattern><template><srai>HELLO</srai></template></category>"
        "<category><pattern>HELLO</pattern><template>hello <get name='who'/></template></category>"
        "<category><pattern>MY NAME IS *</pattern><template><think><set name='who'><star/></set></think>ok</template></category>"
        "<category><pattern>MOOD</pattern><template><condition name='mood'>"
        "<li value='busy'>later</li><li value='*'>sure</li><li>who?</li></condition></template></category>"
        "<category><pattern>BUSY</pattern><template><condition name='mood' value='busy'>yes</condition></template></category>"
    )
    assert say(b, "my name is Dana") == "ok"
    assert say(b, "hi there") == "hello dana"
    assert say(b, "mood") == "who?"
    assert say(b, "mood", mood="busy") == "later"
    assert say(b, "busy") == "yes"
    assert say(b, "mood", mood="fine") == "sure"


def test_random_is_seeded():
    body = "<category><pattern>PICK</pattern><template><random><li>a</li><li>b</li><li>c</li><li>d</li></random></template></category>"
    def seq(seed):
        b = bot(body, seed=seed)
        return [say(b, "pick") for _ in range(12)]

    assert seq(7) == seq(7)
    assert len({tuple(seq(s)) for s in range(5)}) > 1


def test_sets_and_maps():
    b = bot(
        "<category><pattern># <set>teams</set> #</pattern><template>team <star index='2'/> owner "
        "<map name='owners'><star index='2'/></map></template></category>",
        sets={"teams": ["platform", "data platform", "search"]},
        maps={"owners": {"data platform": "Mo", "search": "Ana"}},
    )
    assert say(b, "ask the data platform folks") == "team data platform owner Mo"
    assert say(b, "platform is down") == "team platform owner unknown"


def test_person_first_rest_explode_br():
    b = bot(
        "<category><pattern>SAY *</pattern><template><person/></template></category>"
        "<category><pattern>FR *</pattern><template><first><star/></first>|<rest><star/></rest></template></category>"
        "<category><pattern>EX *</pattern><template><explode><star/></explode></template></category>"
        "<category><pattern>LINES</pattern><template>one<br/>two</template></category>"
    )
    assert say(b, "say I told my team") == "you told your team"
    assert say(b, "fr a b c") == "a|b c"
    assert say(b, "ex abc") == "a b c"
    assert say(b, "lines") == "one\ntwo"


def test_loop_counts():
    b = bot(
        "<category><pattern>COUNT</pattern><template><think><set name='n'>x</set></think>"
        "<condition name='n'><li value='xxx'>done</li>"
        "<li><think><set name='n'><get name='n'/>x</set></think>.<loop/></li></condition></template></category>"
    )
    assert say(b, "count") == "..done"


def test_learn():
    b = bot(
        "<category><pattern>REMEMBER *</pattern><template>ok<learn><category>"
        "<pattern>WHAT DID I SAY</pattern><template>you said <eval><star/></eval></template>"
        "</category></learn></template></category>"
    )
    assert say(b, "what did I say") == ""
    assert say(b, "remember blue") == "ok"
    assert say(b, "what did I say") == "you said blue"


def test_request_response_history():
    b = bot(
        "<category><pattern>A</pattern><template>one</template></category>"
        "<category><pattern>B</pattern><template>before: <request/> / <response/></template></category>"
    )
    say(b, "a")
    assert say(b, "b") == "before: a / one"


def test_long_input_does_not_blow_up():
    b = bot(
        "<category><pattern># A # B # C # D #</pattern><template>hit</template></category>"
        "<category><pattern>*</pattern><template>miss</template></category>"
    )
    text = " ".join(["word"] * 2000) + " a b c"
    t0 = time.time()
    assert say(b, text) == "miss"
    assert time.time() - t0 < 2.0


def test_unknown_tag_warns_not_crashes():
    b = bot("<category><pattern>X</pattern><template>a <date/>b</template></category>")
    assert say(b, "x") == "a b"
    assert any("date" in w for w in b.warnings)


def test_random_never_repeats_back_to_back():
    b = Bot(['<aiml><category><pattern>*</pattern><template><random><li>a</li><li>b</li><li>c</li></random></template></category></aiml>'], seed=3)
    out = [b.respond("x")[0] for _ in range(50)]
    assert all(x != y for x, y in zip(out, out[1:]))
    assert set(out) == {"a", "b", "c"}
