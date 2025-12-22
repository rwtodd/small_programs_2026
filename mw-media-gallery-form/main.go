package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"log"
	"os"
	"regexp"
	"strings"
	"text/template"

	"github.com/rwtodd/Go.WikiAPI/wikiapi"
)

var (
	form      *template.Template
	urlRegex  *regexp.Regexp
	listRegex *regexp.Regexp
)

type Credentials struct {
	UserName string `json:"uname"`
	Password string `json:"pw"`
	ApiUrl   string `json:"apiurl"`
	RestUrl  string `json:"resturl"`
}

func init() {
	var err error
	form, err = template.New("Gallery Form").Parse(`<html>
<form action="https://kb.rwtodd.org/rwt-gallery.php" method="POST">
	{{range .}}<input type="hidden" name="images[]" value="{{.}}">
	{{end}}<input type="submit" value="Launch Gallery Viewer">
</form>
</html>`)
	if err != nil {
		log.Fatalln(err)
	}

	urlRegex = regexp.MustCompile(`<a href="(/images/[^"]*)"`)
	listRegex = regexp.MustCompile(`(?m)^\s*\*`)
}

func readCredentials(fname string) (creds Credentials, err error) {
	fileBytes, err := os.ReadFile(fname)
	if err != nil {
		return
	}

	err = json.Unmarshal(fileBytes, &creds)
	return
}

// find all the URLs that start with /images in the `src` string
func extractURLs(src string) (urls []string) {
	for _, match := range urlRegex.FindAllStringSubmatch(src, -1) {
		urls = append(urls, match[1])
	}
	return
}

func getTitlesFromFile(fname string) []string {
	file, err := os.Open(fname)
	if err != nil {
		log.Fatal(err)
	}
	defer file.Close()

	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		lines = append(lines, scanner.Text()) // Text() strips the newline
	}

	if err := scanner.Err(); err != nil {
		log.Fatal(err)
	}
	return lines
}

func main() {
	var session wikiapi.Session
	credJSON := flag.String("c", "un_pw.json", "A JSON file of credentials for the server")
	infile := flag.String("i", "", "a file of page titles (1 per line)")
	flag.Parse()

	creds, err := readCredentials(*credJSON)
	if err != nil {
		log.Fatalf("Credentials problem! %v", err)
	}

	err = session.Login(creds.ApiUrl, creds.RestUrl, creds.UserName, creds.Password)
	if err != nil {
		log.Fatalf("Error with login! %v", err)
	}
	defer session.Logout()

	// get titles from the input file and the cmdline args...
	var titles []string
	if *infile != "" {
		titles = getTitlesFromFile(*infile)
	}
	if len(flag.Args()) > 0 {
		titles = append(titles, flag.Args()...)
	}

	for _, title := range titles {
		log.Println(title)
		html, err := session.FetchHTML(title)
		if err != nil {
			log.Printf("Error fetching HTML! %v", err)
			return
		}

		wikitext, err := session.FetchWikitext(title)
		if err != nil {
			log.Printf("Error getting wikitext. %v", err)
			return
		}

		urls := extractURLs(html)

		listloc := listRegex.FindStringIndex(wikitext)
		if listloc == nil {
			log.Printf("%s: Couldn't find the list of pages!", title)
			return
		}

		var pageResult strings.Builder
		pageResult.WriteString(wikitext[:listloc[0]])
		err = form.Execute(&pageResult, urls)
		if err != nil {
			log.Printf("%s: Error building the form! %v", title, err)
			return
		}

		pageResult.WriteString("\nPages:\n")
		pageResult.WriteString(wikitext[listloc[0]:])
		err = session.EditFromString(title, pageResult.String(), "Added form for page gallery", "")
		if err != nil {
			log.Printf("%s: Error uploading modified page! %v", title, err)
			return
		}
	}

}
