package main

import (
	"regexp"
	"testing"
)

func TestProcessFilename(t *testing.T) {
	tests := []struct {
		name     string
		filename string
		index    int
		config   Config
		want     string
	}{
		{
			name:     "No changes",
			filename: "file.txt",
			index:    1,
			config:   Config{},
			want:     "file.txt",
		},
		{
			name:     "Simple Regex",
			filename: "foo.txt",
			index:    1,
			config: Config{
				Replacements: []Replacement{
					{Regex: regexp.MustCompile("foo"), Replacement: "bar"},
				},
			},
			want: "bar.txt",
		},
		{
			name:     "Multiple Regex",
			filename: "foo-bar.txt",
			index:    1,
			config: Config{
				Replacements: []Replacement{
					{Regex: regexp.MustCompile("foo"), Replacement: "baz"},
					{Regex: regexp.MustCompile("-"), Replacement: "_"},
				},
			},
			want: "baz_bar.txt",
		},
		{
			name:     "Alpha Clean",
			filename: "File #1 (copy).txt",
			index:    1,
			config: Config{
				AlphaRegex: regexp.MustCompile(`[^a-zA-Z0-9]+`),
			},
			want: "File_1_copy.txt",
		},
		{
			name:     "Alpha with Regex",
			filename: "File #1.txt",
			index:    1,
			config: Config{
				AlphaRegex: regexp.MustCompile(`[^a-zA-Z0-9]+`),
				Replacements: []Replacement{
					{Regex: regexp.MustCompile("File"), Replacement: "Doc"},
				},
			},
			want: "Doc_1.txt",
		},
		{
			name:     "Truncate",
			filename: "really_long_filename.txt",
			index:    1,
			config: Config{
				Truncate:       true,
				TruncateLength: 6,
			},
			want: "really.txt",
		},
		{
			name:     "Truncate Short File",
			filename: "short.txt",
			index:    1,
			config: Config{
				Truncate:       true,
				TruncateLength: 10,
			},
			want: "short.txt",
		},
		{
			name:     "Numbering",
			filename: "file.txt",
			index:    42,
			config: Config{
				NumFormat: "%03d_%s",
			},
			want: "042_file.txt",
		},
		{
			name:     "Combined: Regex -> Alpha -> Truncate -> Num",
			filename: "My Cool Video! [1080p].mp4",
			index:    7,
			config: Config{
				AlphaRegex:     regexp.MustCompile(`[^a-zA-Z0-9]+`),
				NumFormat:      "%02d_%s",
				Truncate:       true,
				TruncateLength: 10,
				Replacements: []Replacement{
					{Regex: regexp.MustCompile("Cool"), Replacement: "Awesome"},
				},
			},
			// 1. Regex: My Awesome Video! [1080p].mp4
			// 2. Alpha: My_Awesome_Video_1080p.mp4
			// 3. Truncate (10 chars): My_Awesome.mp4
			// 4. Num: 07_My_Awesome.mp4
			want: "07_My_Awesome.mp4",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := processFilename(tt.filename, tt.index, tt.config)
			if got != tt.want {
				t.Errorf("processFilename() = %v, want %v", got, tt.want)
			}
		})
	}
}
