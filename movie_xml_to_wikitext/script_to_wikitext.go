package main

import (
	"encoding/xml"
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
)

// SceneContent interface for mixed content in scenes
type SceneContent interface {
	isSceneContent()
}

// Desc section with paragraphs
type Desc struct {
	XMLName xml.Name `xml:"desc"`
	Ps      []string `xml:"p"`
}

func (Desc) isSceneContent() {}

// SpeakerPart for mixed p and sdir in speaker
type SpeakerPart interface {
	isSpeakerPart()
}

// Para paragraph in speaker
type Para struct {
	XMLName xml.Name `xml:"p"`
	Text    string   `xml:",chardata"`
}

func (Para) isSpeakerPart() {}

// Sdir stage direction
type Sdir struct {
	XMLName xml.Name `xml:"sdir"`
	Text    string   `xml:",chardata"`
}

func (Sdir) isSpeakerPart() {}

// Speaker section
type Speaker struct {
	XMLName xml.Name `xml:"speaker"`
	Name    string
	Parts   []SpeakerPart
}

func (Speaker) isSceneContent() {}

// Scene with title and mixed contents (desc/speaker in order)
type Scene struct {
	XMLName  xml.Name
	Title    string
	Contents []SceneContent
}

// UnmarshalXML for Scene to handle mixed desc/speaker in document order
func (s *Scene) UnmarshalXML(d *xml.Decoder, start xml.StartElement) error {
	s.XMLName = start.Name
	for {
		token, err := d.Token()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		switch t := token.(type) {
		case xml.StartElement:
			switch t.Name.Local {
			case "title":
				if err := d.DecodeElement(&s.Title, &t); err != nil {
					return err
				}
			case "desc":
				var desc Desc
				if err := d.DecodeElement(&desc, &t); err != nil {
					return err
				}
				s.Contents = append(s.Contents, desc)
			case "speaker":
				var speaker Speaker
				if err := d.DecodeElement(&speaker, &t); err != nil {
					return err
				}
				s.Contents = append(s.Contents, speaker)
			default:
				// skip unknown elements
				var ignore interface{}
				d.DecodeElement(&ignore, &t)
			}
		case xml.EndElement:
			if t.Name == start.Name {
				return nil
			}
		case xml.CharData:
			// ignore whitespace between elements
		}
	}
}

// UnmarshalXML for Speaker to handle name + mixed p/sdir
func (sp *Speaker) UnmarshalXML(d *xml.Decoder, start xml.StartElement) error {
	sp.XMLName = start.Name
	for {
		token, err := d.Token()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		switch t := token.(type) {
		case xml.StartElement:
			switch t.Name.Local {
			case "name":
				var nameStr string
				if err := d.DecodeElement(&nameStr, &t); err != nil {
					return err
				}
				sp.Name = strings.ToUpper(strings.TrimSpace(nameStr))
			case "p":
				var para Para
				if err := d.DecodeElement(&para, &t); err != nil {
					return err
				}
				sp.Parts = append(sp.Parts, para)
			case "sdir":
				var sdir Sdir
				if err := d.DecodeElement(&sdir, &t); err != nil {
					return err
				}
				sp.Parts = append(sp.Parts, sdir)
			default:
				var ignore interface{}
				d.DecodeElement(&ignore, &t)
			}
		case xml.EndElement:
			if t.Name == start.Name {
				return nil
			}
		case xml.CharData:
			// ignore
		}
	}
}

// Script and Act use standard unmarshaling
type Script struct {
	XMLName xml.Name `xml:"script"`
	Acts    []Act    `xml:"act"`
}

type Act struct {
	XMLName xml.Name `xml:"act"`
	Title   string   `xml:"title"`
	Scenes  []Scene  `xml:"scene"`
}

// normalizeWhitespace collapses all whitespace to single spaces and trims.
// It also converts any bare ampersands (that came from &amp; in the input)
// into literal "&amp;" entities for wikitext, while leaving existing entities
// like &mdash;, &hellip;, etc. untouched.
var ampOrEntityRe = regexp.MustCompile(`&(?:[a-zA-Z0-9#]+;)?`)

func normalizeWhitespace(s string) string {
	s = strings.TrimSpace(s)
	s = strings.Join(strings.Fields(s), " ")

	s = ampOrEntityRe.ReplaceAllStringFunc(s, func(match string) string {
		if len(match) > 1 && strings.HasSuffix(match, ";") {
			// It's a complete entity like &mdash;, &hellip;, &amp;, &#123; etc. → keep as-is
			return match
		}
		// Lone ampersand (or incomplete like &foo) → escape it
		return "&amp;"
	})
	return s
}

// buildSpeakerParagraph turns the mixed parts into one wikitext paragraph string with spans for sdir
func buildSpeakerParagraph(sp Speaker) string {
	var parts []string
	for _, part := range sp.Parts {
		if p, ok := part.(Para); ok {
			text := normalizeWhitespace(p.Text)
			if text != "" {
				parts = append(parts, text)
			}
		} else if sd, ok := part.(Sdir); ok {
			text := normalizeWhitespace(sd.Text)
			// strip surrounding parentheses if present (CSS will add them back)
			text = strings.TrimSpace(text)
			if strings.HasPrefix(text, "(") && strings.HasSuffix(text, ")") {
				text = strings.TrimPrefix(text, "(")
				text = strings.TrimSuffix(text, ")")
				text = strings.TrimSpace(text)
			}
			if text != "" {
				parts = append(parts, "<span class=\"stagedir\">"+text+"</span>")
			}
		}
	}
	return strings.Join(parts, " ")
}

// sceneToWikitext converts a scene to wikitext, grouping consecutive speakers in div
func sceneToWikitext(scene Scene) string {
	var b strings.Builder
	b.WriteString("== " + scene.Title + " ==\n\n")

	i := 0
	for i < len(scene.Contents) {
		content := scene.Contents[i]
		if desc, ok := content.(Desc); ok {
			for _, p := range desc.Ps {
				text := normalizeWhitespace(p)
				if text != "" {
					b.WriteString(text + "\n\n")
				}
			}
			i++
		} else if _, ok := content.(Speaker); ok {
			// collect run of consecutive speakers
			var speakers []Speaker
			for i < len(scene.Contents) {
				if sp, ok := scene.Contents[i].(Speaker); ok {
					speakers = append(speakers, sp)
					i++
				} else {
					break
				}
			}
			// output div
			b.WriteString("<div class=\"scriptdialog\">\n")
			for j, sp := range speakers {
				paraText := buildSpeakerParagraph(sp)
				b.WriteString("<span class=\"speaker\">" + sp.Name + "</span> " + paraText)
				if j < len(speakers)-1 {
					b.WriteString("\n\n")
				} else {
					b.WriteString("\n")
				}
			}
			b.WriteString("</div>\n\n")
		} else {
			i++
		}
	}
	return b.String()
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: go run script_to_wikitext.go <input.xml>")
		fmt.Println("Converts movie script XML to Act_*.wikitext files (one per act).")
		return
	}

	inputPath := os.Args[1]
	f, err := os.Open(inputPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error opening input file: %v\n", err)
		os.Exit(1)
	}
	defer f.Close()

	dec := xml.NewDecoder(f)
	// Make parser lenient with unknown entities (mdash, hellip, etc.)
	// and map them (plus &amp;) so they are preserved literally as entities in output text.
	dec.Strict = false
	dec.Entity = map[string]string{
		"amp":    "&amp;",
		"mdash":  "&mdash;",
		"hellip": "&hellip;",
		// Common additional entities often found in scripts
		"ndash":  "&ndash;",
		"ldquo":  "&ldquo;",
		"rdquo":  "&rdquo;",
		"lsquo":  "&lsquo;",
		"rsquo":  "&rsquo;",
		"nbsp":   "&nbsp;",
		"quot":   "&quot;",
		"apos":   "&apos;",
		"lt":     "&lt;",
		"gt":     "&gt;",
	}

	var script Script
	if err := dec.Decode(&script); err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing XML: %v\n", err)
		os.Exit(1)
	}

	if len(script.Acts) == 0 {
		fmt.Println("No acts found in script.")
		return
	}

	for _, act := range script.Acts {
		if act.Title == "" {
			act.Title = "Untitled_Act"
		}
		actFilename := "Act_" + strings.ReplaceAll(act.Title, " ", "_") + ".wikitext"

		var content strings.Builder
		for _, scene := range act.Scenes {
			if scene.Title == "" {
				scene.Title = "Untitled_Scene"
			}
			content.WriteString(sceneToWikitext(scene))
		}

		if err := os.WriteFile(actFilename, []byte(content.String()), 0644); err != nil {
			fmt.Fprintf(os.Stderr, "Error writing %s: %v\n", actFilename, err)
			os.Exit(1)
		}
		fmt.Println("Written:", actFilename)
	}
}