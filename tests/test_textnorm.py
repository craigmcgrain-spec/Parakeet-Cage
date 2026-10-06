"""Tests for parakeet_cage.textnorm (spoken punctuation).

The fixtures in the first section are verbatim Parakeet Redux outputs for espeak-ng
speech, captured while measuring what the model does with spoken commands:

    spoken:  'How are you question mark See you tomorrow'
    model :  'How are you question mark? See you tomorrow.'
    spoken:  'I sent the file period Did you get it question mark'
    model :  'I sent the file period did you get it, question mark.'
    spoken:  'First item comma second item comma third item'
    model :  'First item comma second item comma third item'
    spoken:  'So that is the plan exclamation mark New paragraph Let us begin'
    model :  'So that is the plan exclamation mark new paragraph let us begin.'
    spoken:  'Is it ready question mark'
    model :  'Is it Reddy question Mark?'

They are the regression net for the three cleanup rules that make this more than a
dictionary lookup: absorbing the model's own punctuation around the command,
collapsing duplicates, and re-capitalising the clause that follows.
"""

from parakeet_cage.textnorm import apply_spoken_punctuation


def test_absorbs_model_punctuation_attached_to_the_command():
    assert apply_spoken_punctuation("How are you question mark? See you tomorrow.") == \
        "How are you? See you tomorrow."


def test_command_mid_utterance_repunctuates_and_capitalises_the_next_clause():
    assert apply_spoken_punctuation("I sent the file period did you get it, question mark.") == \
        "I sent the file. Did you get it?"


def test_maps_commands_that_the_model_left_unpunctuated():
    assert apply_spoken_punctuation("First item comma second item comma third item") == \
        "First item, second item, third item"


def test_new_paragraph_breaks_the_line_and_capitalises():
    assert apply_spoken_punctuation(
        "So that is the plan exclamation mark new paragraph let us begin."
    ) == "So that is the plan!\n\nLet us begin."


def test_command_is_matched_case_insensitively():
    # the model capitalised "Mark" as a proper noun
    assert apply_spoken_punctuation("Is it Reddy question Mark?") == "Is it Reddy?"


def test_repeated_application_changes_nothing_further():
    once = apply_spoken_punctuation("How are you question mark? See you tomorrow.")
    assert apply_spoken_punctuation(once) == once


def test_text_without_commands_is_untouched():
    text = "Nothing to do here at all."
    assert apply_spoken_punctuation(text) == text


def test_empty_text_is_untouched():
    assert apply_spoken_punctuation("") == ""


def test_command_suffix_inside_a_longer_word_is_not_matched():
    assert apply_spoken_punctuation("question marks are useful") == "question marks are useful"


def test_command_is_not_double_punctuated():
    assert apply_spoken_punctuation("wow exclamation mark!") == "wow!"


def test_literal_prefix_leaves_the_word_alone():
    assert apply_spoken_punctuation("during a literal period of time") == \
        "during a period of time"


def test_space_before_punctuation_is_removed_and_one_space_follows():
    assert apply_spoken_punctuation("hello world,next") == "hello world, next"


def test_symbol_commands_join_tightly():
    assert apply_spoken_punctuation("mail me at sign craig underscore mcgrain") == \
        "mail me@craig_mcgrain"


def test_brackets_open_and_close():
    assert apply_spoken_punctuation("see open paren note close paren here") == \
        "see (note) here"


def test_custom_commands_extend_the_default_table():
    assert apply_spoken_punctuation("done winky face", commands={"winky face": ";-)"}) == \
        "done ;-)"


def test_custom_commands_can_override_a_default():
    assert apply_spoken_punctuation("stop period go", commands={"period": "!"}) == \
        "stop! Go"


def test_configuration_can_disable_a_command():
    assert apply_spoken_punctuation("First item comma second", commands={"comma": None}) == \
        "First item comma second"
