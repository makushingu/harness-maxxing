// Syntax highlighting grammars, loaded on demand by markdown.tsx (the first code block with a language).
// The languages a Claude conversation actually contains (aliases come with each grammar: sh, js, ts, html, yml…).
// rehype-highlight is not used: it imports lowlight's whole `common` set (37 grammars) whatever options it gets.
import { createLowlight } from 'lowlight'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import diff from 'highlight.js/lib/languages/diff'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import go from 'highlight.js/lib/languages/go'
import ini from 'highlight.js/lib/languages/ini'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import php from 'highlight.js/lib/languages/php'
import python from 'highlight.js/lib/languages/python'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

export const lowlight = createLowlight({ bash, css, diff, dockerfile, go, ini, java, javascript, json, markdown, php, python, rust, sql, typescript, xml, yaml })
