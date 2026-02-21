# frozen_string_literal: true

require_relative "lib/bulk_rename"

Gem::Specification.new do |spec|
  spec.name          = "bulk_rename"
  spec.version       = BulkRename::VERSION
  spec.authors       = ["Richard Todd"]
  spec.email         = ["dev@example.com"]

  spec.summary       = "Bulk rename tool"
  spec.description   = "Bulk rename tool to apply regexes to the basenames of a lot of files."
  spec.homepage      = "https://github.com/rwtodd/small_programs_2026/bulk-rename/"
  spec.license       = "MIT"
  spec.required_ruby_version = Gem::Requirement.new(">= 3.0.0")

  spec.metadata["homepage_uri"] = spec.homepage

  spec.files = ["bin/bulk-rename", "lib/bulk_rename.rb"]
  spec.bindir        = "bin"
  spec.executables   = ["bulk-rename"]
  spec.require_paths = ["lib"]

  spec.add_dependency "tty-prompt", "~> 0.23"
end
