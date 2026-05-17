# Movie Script XML -- Input to the Program

The schema looks like:

```xml
<script><header> {{just ignore what's in here}} </header>

<act><title>Title of the Act</title>
<scene><title>Scene 1 Title</title>  {{ scene contents described below }} </scene>
<scene><title>Scene 2 Title</title>  {{ scene contents described below }} </scene>
<scene><title>Scene 3 Title</title>  {{ scene contents described below }} </scene>
</act>

<act> {{another act}} </act>
<act> {{another act}} </act>
<act> {{another act}} </act>
</script>
```

Acts can have any number of scenes. Each scene has a mix of `<desc>`-sections and `<speaker>`-sections. There can be any number of them, in any number (after the obligatory scene title alrady shown above).

 - A `desc` section contains some number of `<p>` paragraphs of text (think like HTML paragraphs).
 - A `speaker` section is more structured:

```xml
<speaker><name>BOB</name>
<p>Some text<p>
<sdir>(a stage direction)</sdir>
<p>More text</p>
</speaker>
```

There can be any number of `sdir` and `p` sections, in any order (after the obligatory `name` which should always be in all caps--correct that if you find any that aren't!).

# Wikitext Script -- Output of the program

Each Act should get its own output file in the form "Act\_Name.wikitext" (where the act name is used, of course, and with spaces replaced by underscores).

The acts, as you saw, are made of `<scene>`-sections. Every scene has a mandatory first tag for the title, and it shouldbe rendered in wikitext as a heading...

```xml
<scene><title>The Title</title> ... </scene>
```

... should be rendered as:

```wikitext
== The Title ==
```

Within each scene.. do the following:

## Desc sections
The paragraphs in `desc` sections sould just become wikitext paragraphs (plain paragraphs of text with double-newlines separating them.  So for example:

```xml
<p>Some Text</p>
<p>Some more text</p>
```

... should become:

```wikitext
Some Text

Some more text
```

Copy whatever is in a `<p>`-tag as-is, except change all extra spaces and newlines in a paragraph to a single space (html-style space handling).

## Speaker sections
This is a little trickier.  We want any run of consecutive `<speaker>` sections to be enclosed in a `<div>` in the wikitext output, like this:

```xml
<speaker><name>BOB</name><p>Hello.</p></speaker>
<speaker><name>ALEC</name><p>Oh, hi.</p></speaker>
```

... should become:

```wikitext
<div class="scriptdialog">
<span class="speaker">BOB</span> Hello.

<span class="speaker">ALEC</span> Oh, hi.
</div>
```

Note that, each `<speaker>`-section gets its own wikitext paragraph (with a double-space afterwards, except for the last speaker in the sequence, which just ends with a close of the enclosing `<div>`.  Note that even if there is only one `<speaker>`-section, it still gets surrounded by that div.

When there is a mix of `<p>` and `<sdir>` tags in a speaker section, it all becomes one big paragraph of wikitext, and the `<sdir>`-text becomes a span in that single output paragraph.  Example:

```xml
<speaker><name>BOB</name><p>Hello.</p><sdir>(checks his watch)</sdir><p>Look at the time!</p></speaker>
```

... should become:

```wikitext
<div class="scriptdialog">
<span class="speaker">BOB</span> Hello. <span class="stagedir">checks his watch<span> Look at the time!
</div>
```

Note that: if the stage direction is surrounded by parentheses in the input, these should be stripped from the output (the styling on the span adds them back in!)

When outputting the contents of the input `<p>` and `<sdir>`-tags, copy it as-is, except change all extra spaces and newlines in a paragraph to a single space (html-style space handling). (and of course we already covered removing the enclosing parens around the `sdir`s if they are present).
