#!/usr/bin/env ruby
# frozen_string_literal: true
# encoding: utf-8
#
# cbz-to-mw.rb — Ruby 4.0+ port of the cbz-to-mw comic archive processor.

=begin
cbz-to-mw.rb

Converts CBZ/CBR/zip comic archives into sequentially-renamed WebP (or original) images
and generates a MediaWiki .wikitext index page — exactly like the original Go program
and the PowerShell port.

SYNOPSIS
    ruby cbz-to-mw.rb [options] INPUT_FILE.cbz

DESCRIPTION
    This is a faithful Ruby port of the Go "cbz-to-mw" utility (and matches the
    accompanying PowerShell version byte-for-byte on all outputs).

    - Uses 7zz (7-Zip) to extract the archive.
    - Finds supported images (.jpg .jpeg .webp .png .gif), applies optional basename regex exclude.
    - Pipes each image through ImageMagick "magick" to produce a WebP at the requested quality.
    - Keeps the WebP only if it is strictly smaller than the original; otherwise keeps the
      original bytes (normalizing .jpeg → .jpg on output name when appropriate).
    - Writes images to ./results/ as Cmx-<Title>[_<Issue>]-NNN.<ext>
    - Computes the MediaWiki MD5-sharded directory prefix (first byte of MD5 of the filename).
    - Emits a .wikitext file with the correct Nav template (Comic Book or Graphic Novel),
      the hidden-image gallery form, the [[Media:]] list, and the category — with identical
      whitespace, including 4-space indentation on the submit button and no trailing newline
      after the final category line.

    Images are processed with up to 8 concurrent "magick" invocations (using threads +
    SizedQueue to bound concurrency). Results are collected by original index so that
    output file ordering and the generated .wikitext are always identical to the Go
    reference implementation regardless of completion order.

PARAMETERS / OPTIONS
    -t, --title TITLE
        Comic title. Spaces become underscores in filenames and wiki links.
        Default: "My Comic"

    -i, --issue NUMBER
        Issue number (integer). Use -1 for a Graphic Novel (affects naming, nav template,
        and parenthetical in the output filename). Default: -1

    -q, --quality PERCENT
        WebP quality passed to magick (1-100). Default: 80

    -x, --exclude REGEX
        Skip any extracted file whose basename matches this Ruby regex (e.g. '^zz').
        Default: no exclusion.

    INPUT_FILE
        The archive to process (.cbz, .cbr, .zip, etc.). Required positional argument.

    --7zz COMMAND
        Name or path of the 7-Zip executable. Default: "7zz"
        (Use "7z" on some Windows installations.)

    --magick COMMAND
        Name or path of the ImageMagick v7+ "magick" executable. Default: "magick"

EXAMPLES
    ruby cbz-to-mw.rb -t "Fantastic Four" -i 42 -q 85 ff42.cbz
    ruby cbz-to-mw.rb --title "My Manga" --issue -1 volume_01.cbz
    ruby cbz-to-mw.rb --exclude '^zz' --7zz 7z --magick magick mycomic.cbr

REQUIREMENTS
    - 7-Zip command-line tool (7zz or 7z) in PATH
    - ImageMagick 7+ "magick" command in PATH
    - Ruby 3.0+ (written for Ruby 4.0 idioms but compatible with 3.x)

OUTPUT
    ./results/  — contains the renamed image files and the generated .wikitext
    ./out_tmp/  — temporary extraction directory (left behind for inspection, like the Go version)

NOTES
    - All filename construction, MD5 sharding, wiki template text, and whitespace
      are reproduced exactly so that the generated .wikitext files are byte-identical
      to the Go reference implementation.
    - Non-image files and excluded files are ignored.
    - Errors on individual images are reported but do not abort the whole run (matching Go).
    - Image conversion uses a concurrency limit of 8 (via Ruby threads + SizedQueue);
      the original input filename sort order is strictly preserved for all outputs.
=end

require "optparse"
require "fileutils"
require "digest/md5"
require "open3"
require "thread"

IMAGE_EXTS = %w[.jpg .jpeg .webp .png .gif].freeze

# ------------------------ CLI ------------------------

title       = "My Comic"
issue       = -1
quality     = 80
exclude_str = nil
seven_zip   = "7zz"
magick      = "magick"
input_file  = nil

parser = OptionParser.new do |opts|
  opts.banner = "Usage: #{$PROGRAM_NAME} [options] INPUT_FILE"

  opts.on("-t", "--title TITLE", "Comic title (spaces → underscores)") { |v| title = v }
  opts.on("-i", "--issue NUMBER", Integer, "Issue number (-1 = Graphic Novel)") { |v| issue = v }
  opts.on("-q", "--quality PERCENT", Integer, "WebP quality (default 80)") { |v| quality = v }
  opts.on("-x", "--exclude REGEX", "Regex to exclude filenames by basename") { |v| exclude_str = v }
  opts.on("--7zz COMMAND", "7-Zip executable (default 7zz)") { |v| seven_zip = v }
  opts.on("--magick COMMAND", "ImageMagick magick executable (default magick)") { |v| magick = v }

  opts.on("-h", "--help", "Show this help") { puts opts; exit }
end

begin
  parser.parse!
rescue OptionParser::InvalidOption, OptionParser::MissingArgument => e
  warn e.message
  warn parser
  exit 1
end

if ARGV.size != 1
  warn "Must give an input file (.cbr/.cbz)!"
  warn parser
  exit 1
end
input_file = ARGV[0]

exclude_regex = exclude_str ? Regexp.new(exclude_str) : nil

# ------------------------ Core constants ------------------------

temp_dir   = "out_tmp"
result_dir = "results"

# ------------------------ Preparation ------------------------

FileUtils.rm_rf(temp_dir) if Dir.exist?(temp_dir)
FileUtils.mkdir_p([temp_dir, result_dir])

puts input_file

# ------------------------ Extract ------------------------

unless system(seven_zip, "e", "-o#{temp_dir}", input_file)
  abort "7zz failed with exit code #{$?.exitstatus}"
end

# ------------------------ Collect images (lexical sort on full path) ------------------------

jpegs = Dir.glob(File.join(temp_dir, "*"))
           .select { |f| File.file?(f) }
           .select { |f|
             base = File.basename(f)
             ext  = File.extname(f).downcase
             (exclude_regex.nil? || !exclude_regex.match?(base)) && IMAGE_EXTS.include?(ext)
           }
           .sort

abort "No JPEG files found in archive." if jpegs.empty?

# ------------------------ Process each image (concurrent, up to 8 magick processes) ------------------------
# We mirror the Go implementation's approach: launch a thread per image, gate them with
# a SizedQueue semaphore (capacity 8), and store results by their original index so that
# lexical input order is preserved for output filenames and the .wikitext even when
# individual magick runs finish out-of-order.
#
# Note: process_image no longer needs the index; position in the results array carries it.

def process_image(quality, path, magick_cmd)
  jpg_data = File.binread(path)
  ext = File.extname(path).downcase

  case ext
  when ".webp"
    return { content: jpg_data, ext: ".webp", err: nil }
  when ".png"
    input_str, out_ext = "png:-", ".png"
  when ".gif"
    input_str, out_ext = "gif:-", ".gif"
  else
    input_str, out_ext = "jpeg:-", ".jpg"
  end

  quality_str = "#{quality}%"
  begin
    Open3.popen3(magick_cmd, input_str, "-quality", quality_str, "webp:-") do |stdin, stdout, stderr, wait_thr|
      stdin.binmode
      stdout.binmode
      stdin.write(jpg_data)
      stdin.close_write
      webp_data = stdout.read
      stderr_text = stderr.read
      status = wait_thr.value
      unless status.success?
        return { content: nil, ext: nil, err: "magick failed: exit #{status.exitstatus}, stderr: #{stderr_text}" }
      end

      if webp_data.bytesize < jpg_data.bytesize
        { content: webp_data, ext: ".webp", err: nil }
      else
        { content: jpg_data, ext: out_ext, err: nil }
      end
    end
  rescue => e
    { content: nil, ext: nil, err: e.message }
  end
end

# Concurrent execution with bounded parallelism (8) and order preservation via index.
results = Array.new(jpegs.size)
semaphore = SizedQueue.new(8)
threads = []

jpegs.each_with_index do |path, i|
  threads << Thread.new(i, path) do |index, file_path|
    semaphore.push(true) # acquire slot (blocks this thread if 8 already running)
    begin
      results[index] = process_image(quality, file_path, magick)
    ensure
      semaphore.pop # release slot
    end
  end
end

threads.each(&:join)

# ------------------------ Build names + write images + collect page data ------------------------

if issue == -1
  issue_name = title.gsub(" ", "_")
else
  issue_name = "#{title} #{format("%03d", issue)}".gsub(" ", "_")
end

pages = []

results.each_with_index do |res, idx|
  if res[:err]
    warn "Error processing image #{idx} (#{jpegs[idx]}): #{res[:err]}"
    next
  end

  seq = format("%03d", idx + 1)
  internal = "Cmx-#{issue_name}-#{seq}#{res[:ext]}"

  # MD5 sharded dir: first byte of MD5 as two hex chars → "x/xx"
  digest = Digest::MD5.hexdigest(internal)
  first_byte_hex = digest[0, 2]
  md5_dir = "#{first_byte_hex[0]}/#{first_byte_hex}"

  pages << {
    page_num: idx + 1,
    fname: internal,
    md5_dir: md5_dir
  }

  File.binwrite(File.join(result_dir, internal), res[:content])
end

abort "No images were successfully processed." if pages.empty?

# ------------------------ Generate exact wikitext (matches Go binary output) ------------------------

parenthetical = (issue == -1 ? "Graphic_Novel" : "Comic_Book_Issue")
wikitext_path = File.join(result_dir, "#{issue_name}_(#{parenthetical}).wikitext")

# Navigation block (different for Graphic Novel vs regular comic)
nav_block = if issue == -1
  <<~NAV.chomp
    {{Graphic Novel Nav
    | 1 = #{title}
    | 2 = #{pages.first[:fname]}
    }}
  NAV
else
  padded = format("%03d", issue)
  prev_link = if issue == 1
    "[[#{title} (Comic Book Series)|Series]]"
  else
    prev_padded = format("%03d", issue - 1)
    "[[#{title} #{prev_padded} (Comic Book Issue)|Issue #{prev_padded}]]"
  end
  next_padded = format("%03d", issue + 1)

  <<~NAV.chomp
    {{Comic Book Nav
    | 1 = #{title}
    | 2 = #{padded}
    | 3 = #{pages.first[:fname]}
    | 4 = #{prev_link}
    | 5 = [[#{title} #{next_padded} (Comic Book Issue)|Issue #{next_padded}]]
    }}
  NAV
end

# The four-space indented hidden inputs for the gallery form
hidden_inputs = pages.map do |p|
  "    <input type=\"hidden\" name=\"images[]\" value=\"/images/#{p[:md5_dir]}/#{p[:fname]}\">"
end.join("\n")

# The bullet list of pages
page_list = pages.map do |p|
  pp = format("%03d", p[:page_num])
  "* [[Media:#{p[:fname]}|Page #{pp}]]"
end.join("\n")

# Assemble everything with a single HEREDOC.
# .chomp on the outer heredoc guarantees no trailing newline after the category line
# (exactly matching the Go binary's output).
content = <<~WIKI.chomp
#{nav_block}
<html>
<form action="https://kb.rwtodd.org/rwt-gallery.php" method="POST">
#{hidden_inputs}
    <input type="submit" value="Launch Gallery Viewer">
</form>
</html>
Pages:
#{page_list}

[[Category:Comic Book Issue]]
WIKI

File.write(wikitext_path, content, encoding: "UTF-8")

puts "Wrote #{wikitext_path} and #{pages.size} image(s) to #{result_dir}/"