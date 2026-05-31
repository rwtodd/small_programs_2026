(Note for me: the session is: grok --resume 019e7c59-4d01-75d3-9559-5e8844dd46e6 )

# Basics 

- I would like the program to be written in Python
  - The goal of the program is to take an ebook which has been formatted and uploaded to a mediawiki site, and do a best-effort translation to xhtml+css in an epub3.3 file.
  - call it `mwbook-to-epub`
  - use `uv` as a dependency-and-build-tool along with its default backend
  - set .python-version to 3.14
  - make it so the tool could be installed with `uv tool install .` if wanted
  - Note: uv and python 3.14.5 are already installed.

- Local (non-pypi) Dependencies
  - For downloading from the mediawiki, use a dependency on the "rwt-wikiapi" project in ../../small\_python\_packages/wikiapi
  - For creating the epub, use a dependency on the "rwt-epub" project in ../../small\_python\_packages/epub

- For 3rd-party dependencies, I would like for the program to stick to well-known dependencies when possible, but after a short time period I probably won't need this program anymore, so use whatever works and makes the project easiest

- I would like the program to produce a log as it goes, so I can check it for aspects of the output that may need adjusting

- I would like the 3 stages of the program to be able to be restarted ... in other words, I'd like to restart from stage 2 when I want, without re-doing stage 1 for a project.  This is because I may need to adjust the intermediate files and re-run, to get the output I want.

# Stages of the program

Ideally each stage could be run separately, so the program could be restarted from stage 2, for example, without re-downloading everything.  So each stage should leave files behind that allow the program to pick up where it left off, and redo only the desired stages after tweaks have been made.

## Stage 1: the TOC

Take an input file that is a wikitext TOC page for a book. (Also for extra credit allow the user to give the page name for the TOC, and download it from the wiki using the rwt\_wikiapi library).  An example TOC page is provided in the file:

    ./example\_inputs/32\_Paths\_of\_Wisdom\_(PF\_Case).wikitext

Go down all the links on the page, downloading their contents as wikitext (using the rwt\_wikiapi library already written).  Credentials to pass tot he rwt\_wikiapi library would be given by the user on the command-line as a JSON file (like the wiki-xfer utility, which also uses the rwt\_wikiapi library)

The TOC page might also have an image reference which will invariably be the cover image, so download that and remember it is the cover image.  Convert GIF/PNG/JPEG to WEBP format using `magick` at 80% quality.  Assuming the converted WEBP is smaller than the original use that, otherwise just use the original file.  SVGs should pass through as SVGs, an WEBPs should pass through as WEBP.

There may be stray links on the TOC that are not to chapters... the actual chapter links will always be in part of either an ordered or unordered list, so focus on those.  Sometimes there will be multiple lists in the TOC page.. just take all the links in the order they are found.

As each chapter file is downloaded, scan the wikitext for [[File:...]] or [[:File:...]] or [[Media:...]] or <gallery> sections... and download all of those images, again converting to WEBP if the WEBP turns out smaller.  Keep track of the images downloaded and their converted extensions, so that you don't download the same image multiple times if it is referenced multiple times. This can happen a lot.

Note: you are NOT crawling the pages looking for more wikitext pages to download... all the chapters in the book will be referenced from the TOC page.  Any other wiki links in the chapters to other pages will generally just be converted to a non-link (details below).

## Stage 2: XHTML conversion

Convert each chapter (wikitext page) to xhtml suitable for use in an epub3.3 file.

## Stage 3: EPUB creation

Build the epub3.3 file from the converted chapters made during step 2.  Use the already-written rwt_epub library.



# Details of the Wikitext conversion to xhtml (Stage 2 above)

An example file from a real wikitext book is:

    ./example\_inputs/Path\_1\_(32\_Paths\_PFC).wikitext

## Pages -> Chapters

A Wikitext Page is an epub chapter (a single xhtml file).  So the 1:1 conversion there is easy... the page title (with underscores converted to spaces) should become a prominent (h1, maybe?) heading at the top of the converted xhtml file.  This is because on the mediawiki the page title automatically appears at the top of the page, even though it is not present in the wikitext itself. Note: many times the page title will have a parenthetical suffix to mark the page as part of a book... remove this when printing the chapter title at the top of the xhtml file since the whole resulting EPUB is for that book and there is no ambiguity.

## Basic Formatting

All basic formatting that maps to xhtml tags supported by epub3.3 should be simply translated to xhtml.  This includes bold/italic.. ordered list, unordered list, definition list, spans, divs, and more.

## Hangling Tables

Some pages use tables, and these should be translated to html tables.


## Handling Links

When a link is to a page in the list provided by the TOC, then it should be converted to an html link.  When it is to another wiki page *not* included in the TOC, then it should just be replaced with the link text with no link present, and the instance should be logged with a location in case something needs to be adjusted manually.

Links to 3rd-party sites can remain links in the converted epub.

### "Next chapter" links

In many documents the last paragraph (often there is a line after it which contains the page category, but this is the last line of visible text) ... the last paragraph will consist of right arrows and a link to the next page:

     &rarr; [[a link]] &rarr;

... these can all be removed from the document, since in an EPub you get to the next chapter by simply turning the page.


## Handling Images

When an image is referenced as a centered thumbnail, then the image should be placed centered and arranged to take 90% of the width of the page via CSS.  Make sure it is the full-scale image so that epub viewers (like Apple Books on iOS) can enlarge and pinch-to-zoom it.

When an image is referenced as a right/left thumbnail, then use media queries with CSS to wither produce the image float: right/left at 50% or so of the width of the screen... or if the screen is narrow then make it take the majority of the screen width centered.  The point is to make sure there is enough room on the side of the image for text to look natural, or if it's better to just center the image and put the text below it instead.  With CSS queries, this decision point can be fine-tuned without changing the xhtml page contents.

Wikitext allows for an image gallery view.  In this case just produce the images in a single centered column at most of the page width (again, via CSS).

In all cases, when there are captions, produce html to put a caption under the image just like the original, and styled by CSS so it is tweak able.

## Collapsable Tables

Some files have tables with "collapsible" class added, to hide/show content.  Here is how I convert those to EPUB when I last did that manually:

Use CSS like this:

    div.rwt-qa {
      margin-bottom: 1ex;
      padding: 0.3em;
      border-width: 1px;
      border-style: solid;
    }
    
    div.rwt-qa > p {
      opacity: 0.2;
      transition: opacity 0.5s ease;
    }
    
    div.rwtShown > p {
      opacity: 1;
    } 

… then, only for chapters that actually use hiding capability... the xhtml `<head>` says:

    <script>
    function rwtShowHide(element) {
        element.classList.toggle('rwtShown');
      }
    </script>

… and use it like this:

    <div class="rwt-qa" onclick="rwtShowHide(this)"><p>hello</p></div>


## Templates to Process

The following are templates I made (in the Template namespace) that would need to be supported in order to process pages well.

Templates which are NOT in the below set can be skipped over (with no text inside).. but the instance should be logged with location so I can manually verify that nothing is wrong.  The one exception is if the top of the page is a reference to a template ending in the word "Nav"... these can always be skipped and will be on most pages.


### BibleVerse

    <includeonly>[[{{{1}}} (NKJV)#V{{{2}}}|{{{3|{{{1}}}:{{{2}}}}}}]]</includeonly><noinclude>
    == Usage ==
    <pre>
      {{BibleVerse|Genesis 10|11}} ==> 
         [[Genesis 10 (NKJV)#V11|Genesis 10:11]]
      {{BibleVerse|Genesis 10|11|that Genesis verse}} ==> 
         [[Genesis 10 (NKJV)#V11|that Genesis verse]]
    </pre>
    </noinclude>

### Center

    <includeonly><div class="center" style="width:auto; margin-left:auto; margin-right:auto;">{{{1}}}</div></includeonly><noinclude>
    == Usage ==
    <pre>
    {{Center|Here's what is centered}}
    </pre></noinclude>

### Hebrew text

    <span style="font-family: 'Times New Roman', times, serif; font-size: 150%; line-height:100%;">{{{1}}}</span><noinclude>
    == Usage ==
    <pre>
    {{hebrew text|&#x5d0;&#x5b8;}}
    </pre>
    
    ... which enlarges the text to 150% and sets the font family to 'times'.  It's intended to make hebrew text larger and easier to read.
    </noinclude>


### InlineFraction

    <includeonly>{{#if:{{{wn|}}}|{{{wn}}}&#x202f;|}}<sup style="vertical-align:text-top; font-size:80%">{{{1}}}</sup>/<sub style="vertical-align:text-bottom; font-size:80%">{{{2}}}</sub></includeonly><noinclude>
    == Usage ==
    Render a fraction inline...
    <pre>
     it is {{InlineFraction|wn=12|3|4}}. ==>
    </pre>
    it is 12&#x202f;<sup style="vertical-align:text-top; font-size:80%">3</sup>/<sub style="vertical-align:text-bottom; font-size:80%">4</sub>.
    
    <pre>
     here: {{InlineFraction|10|27}}.  ==>
    </pre>
    here: <sup style="vertical-align:text-top; font-size:80%">10</sup>/<sub style="vertical-align:text-bottom; font-size:80%">27</sub>.
    
    It formats the fraction the best it can, and puts a thin non-breaking space between the whole number and the fraction.
    </noinclude>

### JesusText

    <includeonly><span class="rwtjesustxt">{{{1}}}</span></includeonly><noinclude>
    == Usage ==
    Words of Christ in a special color via css (blue in light mode)...
    <pre>
      {{JesusText|Hello Everyone}} ==>
    </pre>
    <span class="rwtjesustxt">Hello Everyone</span>
    </noinclude>

### Smallcaps

    <includeonly><span style="font-variant:small-caps">{{{1}}}</span></includeonly><noinclude>
    '''Usage'''
    <pre>
    {{Smallcaps|One Two Three}}
    </pre>
    </noinclude>

### StrongHebrew

    <includeonly>[https://biblehub.com/hebrew/{{{1}}}.htm {{{2|Strong's {{{1}}}}}}]</includeonly><noinclude>
    == Usage ==
    <pre>
      {{StrongHebrew|7814}} ==> 
         [https://biblehub.com/hebrew/7814.htm Strong's 7814]
      {{StrongHebrew|7814|Laughter}} ==> 
         [https://biblehub.com/hebrew/7814.htm Laughter]
    </pre>
    </noinclude>

### Clear

    <div style="clear:{{{1|both}}};"></div><noinclude>This template clears floats... it can take an argument for 'left' or 'right'</noinclude>


