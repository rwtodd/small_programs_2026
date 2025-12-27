package main

import (
	"bytes"
	"crypto/md5"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"text/template"
)

const (
	tempDir   = "out_tmp"
	resultDir = "results"
)

// result holds the processed image data to be added to the mediawiki in order
type result struct {
	Index   int
	Content []byte
	Ext     string
	Err     error
}

var (
	issueWikiText *template.Template
)

func init() {

	funcMap := template.FuncMap{
		"add": func(a, b int) int { return a + b },
	}
	var err error
	issueWikiText, err = template.New("Wikitext Form").Funcs(funcMap).Parse(`
{{- define "GraphicNovel"}}Graphic Novel Nav
| 1 = {{.Title}}
| 2 = {{(index .Pages 0).Fname}}
{{end -}}

{{define "ComicBook"}}Comic Book Nav
| 1 = {{.Title}}
| 2 = {{printf "%03d" .IssueNum}}
| 3 = {{(index .Pages 0).Fname}}
| 4 = {{if eq .IssueNum 1}}[[{{.Title}} (Comic Book Series)|Series]]{{else}}[[{{.Title}} {{printf "%03d" (add .IssueNum -1)}} (Comic Book Issue)|Issue {{printf "%03d" (add .IssueNum -1)}}]]{{end}}
| 5 = [[{{.Title}} {{printf "%03d" (add .IssueNum 1)}} (Comic Book Issue)|Issue {{printf "%03d" (add .IssueNum 1)}}]]
{{end -}}

{{"{{"}}{{if eq .IssueNum -1}}{{template "GraphicNovel" .}}{{else}}{{template "ComicBook" .}}{{end}}{{"}}"}}
<html>
<form action="https://kb.rwtodd.org/rwt-gallery.php" method="POST">
    {{range .Pages}}<input type="hidden" name="images[]" value="/images/{{.MD5Dir}}/{{.Fname}}">
    {{end -}}
	<input type="submit" value="Launch Gallery Viewer">
</form>
</html>
Pages:
{{range .Pages}}* [[Media:{{.Fname}}|Page {{printf "%03d" .PageNum}}]]
{{end}}
[[Category:Comic Book Issue]]`)
	if err != nil {
		log.Fatalln(err)
	}

}

func main() {
	// 1. Command line arguments
	title := flag.String("title", "My Comic", "Comic title (e.g. Fantastic Four)")
	issue := flag.Int("issue", -1, "Issue of the comic (-1 for graphic novel)")
	quality := flag.Int("quality", 80, "Webp conversion quality")
	excludePattern := flag.String("exclude", "", "Regex pattern to exclude filenames (e.g. '^zz')")
	flag.Parse()

	if flag.NArg() != 1 {
		flag.Usage()
		log.Fatalln("Must give an input file (.cbr/.cbz)!")
	}
	inputFile := flag.Args()[0]

	// Pre-compile regex if provided
	var excludeRegex *regexp.Regexp
	if *excludePattern != "" {
		var err error
		excludeRegex, err = regexp.Compile(*excludePattern)
		if err != nil {
			log.Fatalf("Invalid regex pattern: %v", err)
		}
	}

	// 2. Prepare temp directory
	os.RemoveAll(tempDir)
	if err := os.MkdirAll(tempDir, 0755); err != nil {
		log.Fatalf("Failed to create temp dir: %v", err)
	}

	if err := os.MkdirAll(resultDir, 0755); err != nil {
		log.Fatalf("Failed to create results dir: %v", err)
	}

	log.Println(inputFile)
	// 3. Extract archive
	cmd7z := exec.Command("7zz", "e", "-o"+tempDir, inputFile)
	if err := cmd7z.Run(); err != nil {
		log.Fatalf("7zz failed: %v", err)
	}

	// 4. Find and sort JPEGs
	files, _ := filepath.Glob(filepath.Join(tempDir, "*"))
	var jpegs []string
	for _, f := range files {

		// Apply Regex Exclusion
		if excludeRegex != nil {
			fileName := filepath.Base(f)
			if excludeRegex.MatchString(fileName) {
				continue
			}
		}

		ext := strings.ToLower(filepath.Ext(f))
		if ext == ".jpg" || ext == ".jpeg" || ext == ".webp" || ext == ".png" {
			jpegs = append(jpegs, f)
		}
	}
	sort.Strings(jpegs)

	if len(jpegs) == 0 {
		log.Fatal("No JPEG files found in archive.")
	}

	// 5. Concurrent Processing
	numJpegs := len(jpegs)
	results := make([]*result, numJpegs)
	var wg sync.WaitGroup
	semaphore := make(chan struct{}, 5) // Limit to 5 parallel magick processes

	for i, path := range jpegs {
		wg.Add(1)
		go func(index int, filePath string) {
			defer wg.Done()
			semaphore <- struct{}{}        // Acquire
			defer func() { <-semaphore }() // Release

			results[index] = processImage(index, *quality, filePath)
		}(i, path)
	}
	wg.Wait()

	// 6. Get it all written to the output dir, and build up a structure for the template
	var issueName string
	if *issue == -1 {
		issueName = strings.ReplaceAll(*title, " ", "_")
	} else {
		issueName = strings.ReplaceAll(fmt.Sprintf("%s %03d", *title, *issue), " ", "_")
	}
	type Page struct {
		PageNum int
		Fname   string
		MD5Dir  string
	}
	wtextdata := struct {
		Title    string
		IssueNum int
		Pages    []*Page
	}{
		Title:    *title,
		IssueNum: *issue,
		Pages:    nil,
	}
	for _, res := range results {
		if res.Err != nil {
			log.Printf("Error processing image %d: %v", res.Index, res.Err)
			continue
		}

		// Generate filename: .webp or .jpeg
		internalImgName := fmt.Sprintf("Cmx-%s-%03d%s", issueName, res.Index+1, res.Ext)
		md5byte := fmt.Sprintf("%02x", md5.Sum([]byte(internalImgName))[0])
		md5dir := fmt.Sprintf("%s/%s", md5byte[0:1], md5byte)
		wtextdata.Pages = append(wtextdata.Pages, &Page{PageNum: res.Index + 1, Fname: internalImgName, MD5Dir: md5dir})
		err := os.WriteFile(filepath.Join(resultDir, internalImgName), res.Content, 0644)
		if err != nil {
			log.Fatalf("Error creating one of the image files! %v", err)
		}
	}

	// 7. Write the template file...
	var parenthetical string
	if *issue == -1 {
		parenthetical = "Graphic_Novel"
	} else {
		parenthetical = "Comic_Book_Issue"
	}
	issueFile := filepath.Join(resultDir, fmt.Sprintf("%s_(%s).wikitext", issueName, parenthetical))
	issueWTxtFile, err := os.Create(issueFile)
	if err != nil {
		log.Fatalf("Could not create output file! %v", err)

	}
	defer issueWTxtFile.Close()
	err = issueWikiText.Execute(issueWTxtFile, wtextdata)
	if err != nil {
		log.Fatalf("Error exectuing template! %v", err)
	}
}

func processImage(index, quality int, path string) *result {
	// 4.a Read all bytes
	jpgData, err := os.ReadFile(path)
	if err != nil {
		return &result{Err: err}
	}

	if strings.HasSuffix(path, ".webp") {
		// just return the data since it's already webp
		return &result{Index: index, Content: jpgData, Ext: ".webp"}
	}

	// 4.b Run magick
	// magick jpeg:- -format '%w %h\n' -write info:fd:2 -quality 75% webp:-
	var inputStr string
	var inputExt string
	if strings.HasSuffix(path, "png") || strings.HasSuffix(path, "PNG") {
		inputStr = "png:-"
		inputExt = ".png"
	} else {
		inputStr = "jpeg:-"
		inputExt = ".jpg"
	}
	qualityStr := fmt.Sprintf("%d%%", quality)
	cmd := exec.Command("magick", inputStr, "-quality", qualityStr, "webp:-")
	cmd.Stdin = bytes.NewReader(jpgData)

	var stdoutBuf, stderrBuf bytes.Buffer
	cmd.Stdout = &stdoutBuf
	cmd.Stderr = &stderrBuf

	if err := cmd.Run(); err != nil {
		return &result{Err: fmt.Errorf("magick failed: %v, stderr: %s", err, stderrBuf.String())}
	}

	webpData := stdoutBuf.Bytes()

	// 4.c Size comparison
	if len(webpData) < len(jpgData) {
		return &result{Index: index, Content: webpData, Ext: ".webp"}
	}
	return &result{Index: index, Content: jpgData, Ext: inputExt}
}
