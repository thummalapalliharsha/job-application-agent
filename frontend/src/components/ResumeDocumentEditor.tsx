import { Mark, Node as TiptapNode, type JSONContent } from '@tiptap/core'
import type { Editor as TiptapEditor } from '@tiptap/core'
import { NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer, EditorContent, useEditor, type NodeViewProps } from '@tiptap/react'
import { Fragment as PMFragment } from '@tiptap/pm/model'
import { TextSelection } from '@tiptap/pm/state'
import StarterKit from '@tiptap/starter-kit'
import Gapcursor from '@tiptap/extension-gapcursor'
import { GapCursor } from '@tiptap/pm/gapcursor'
import TextAlign from '@tiptap/extension-text-align'
import { useEffect, useMemo, useState, type CSSProperties, type FormEvent, type ReactNode } from 'react'
import { apiUrl } from '../apiUrl'
import { LoadingStatus } from './LoadingStatus'

type SourceRef = { source_type: string; source_id: string }
type ResumeRun = { text: string; marks: Array<Record<string, any>>; source_refs: SourceRef[] }
type ResumeBlock = Record<string, any> & { id: string; type: string; edit_policy: string; formatting: Record<string, any>; source_refs: SourceRef[]; runs?: ResumeRun[] }
type ResumeSection = Record<string, any> & { id: string; type: string; title: string | null; required: boolean; formatting: Record<string, any>; blocks: ResumeBlock[] }
type ResumeDocument = Record<string, any> & { application_id: string; revision_id: string; content: { sections: ResumeSection[] }; source_references: SourceRef[] }
type EditLedgerItem = { block_id: string; block_type: string; edited: true; original_text: string; edited_text: string; source_refs: SourceRef[]; original_revision_id: string; formatting_changed: boolean }
type ApiResponse<T> = T & { decision?: string; error?: string }

const FONT_SIZES = [9.1, 9.2, 10, 11, 12, 13, 18]
const LINE_SPACINGS = [1, 1.1, 1.15]
const ALIGNMENTS = ['left', 'center', 'right'] as const
const SPACING_PRESETS = [0, 0.5, 1, 1.5, 2, 3, 4, 6]
const EDITABLE_TEXT_TYPES = new Set(['summary_paragraph', 'project_entry', 'project_bullet', 'experience_entry', 'experience_bullet', 'education_line', 'certification_entry'])
const BULLET_TYPES = new Set(['project_bullet', 'experience_bullet'])

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function stableStringify(value: any): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function stripKeys(value: Record<string, any>, keys: string[]): Record<string, any> {
  const result = { ...value }
  keys.forEach((key) => delete result[key])
  return result
}

function editableTextBlock(block: ResumeBlock): boolean {
  return block.edit_policy === 'editable_source_backed' || EDITABLE_TEXT_TYPES.has(block.type)
}

function modelToEditorContent(model: ResumeDocument): JSONContent {
  return {
    type: 'doc',
    content: model.content.sections.map((section) => ({
      type: 'resumeSection',
      attrs: { meta: stripKeys(section, ['blocks']) },
      content: section.blocks.map((block) => {
        if (block.type === 'skill_group') return {
          type: 'editableSkillGroup',
          attrs: { meta: stripKeys(block, ['items', 'formatting']), formatting: clone(block.formatting || {}) },
          content: [{ type: 'text', text: (block.items || []).map((item: any) => item.text).join(', ') }],
        }
        if (block.type === 'layout_paragraph') return { type: 'layoutParagraph', attrs: { block: clone(block) } }
        if (editableTextBlock(block)) {
          const meta = stripKeys(block, ['runs', 'formatting'])
          meta.edit_policy = 'editable_source_backed'
          return {
            type: 'editableFact',
              attrs: {
                meta,
                formatting: clone(block.formatting || {}),
                textAlign: Object.prototype.hasOwnProperty.call(block.formatting || {}, 'alignment') ? block.formatting.alignment : null,
              },
              content: (block.runs || []).flatMap((run) => {
                const marks: Array<{ type: string; attrs?: Record<string, any> }> = (run.marks || []).map((mark) => mark.type === 'link'
                  ? { type: 'link', attrs: { href: mark.href } }
                  : { type: mark.type })
                marks.push({ type: 'sourceRefs', attrs: { refs: clone(run.source_refs || []) } })
                return run.text ? [{ type: 'text', text: run.text, ...(marks.length ? { marks } : {}) }] : []
              }),
          }
        }
        return { type: 'protectedFact', attrs: { block: clone(block) } }
      }),
    })),
  }
}

function collectSourceRefs(value: any): SourceRef[] {
  const found = new Map<string, SourceRef>()
  const walk = (node: any) => {
    if (Array.isArray(node)) {
      node.forEach(walk)
      return
    }
    if (!node || typeof node !== 'object') return
    const keys = Object.keys(node)
    if (keys.length === 2 && keys.includes('source_type') && keys.includes('source_id') &&
      typeof node.source_type === 'string' && typeof node.source_id === 'string') {
      const key = `${node.source_type}\u0000${node.source_id}`
      found.set(key, { source_type: node.source_type, source_id: node.source_id })
      return
    }
    Object.values(node).forEach(walk)
  }
  walk(value)
  const compare = (a: string, b: string) => a < b ? -1 : a > b ? 1 : 0
  return [...found.values()].sort((a, b) => compare(a.source_type, b.source_type) || compare(a.source_id, b.source_id))
}

function inlineNodesToRuns(nodes: JSONContent[] | undefined, blockRefs: SourceRef[]): ResumeRun[] {
  const runs: ResumeRun[] = []
  for (const child of nodes || []) {
    if (child.type !== 'text' && child.type !== 'hardBreak') {
      throw new Error(`Unsupported editor node in source-backed text: ${child.type || 'unknown'}`)
    }
    const marks: Array<Record<string, any>> = []
    let runRefs: SourceRef[] = clone(blockRefs)
    let sawSourceRefs = false
    for (const mark of child.marks || []) {
      if (mark.type === 'bold' || mark.type === 'italic' || mark.type === 'underline') {
        marks.push({ type: mark.type })
      } else if (mark.type === 'link') {
        const href = mark.attrs?.href
        if (typeof href !== 'string') throw new Error('Malformed hyperlink mark.')
        marks.push({ type: 'link', href })
      } else if (mark.type === 'sourceRefs') {
        if (sawSourceRefs || !Array.isArray(mark.attrs?.refs)) throw new Error('Malformed or duplicate source-reference mark.')
        runRefs = clone(mark.attrs.refs as SourceRef[])
        sawSourceRefs = true
      } else {
        throw new Error(`Unsupported text formatting mark: ${mark.type}`)
      }
    }
    runs.push({ text: child.type === 'hardBreak' ? '\n' : String(child.text || ''), marks, source_refs: runRefs })
  }
  if (!runs.length) runs.push({ text: '', marks: [], source_refs: clone(blockRefs) })
  return runs
}

function editorContentToModel(content: JSONContent, original: ResumeDocument): ResumeDocument {
  if (content.type !== 'doc' || !Array.isArray(content.content)) throw new Error('The editor document root is malformed.')
  const originalSections = new Map(original.content.sections.map((section) => [section.id, section]))
  const originalBlocks = new Map(original.content.sections.flatMap((section) => section.blocks.map((block) => [block.id, block] as const)))
  const usedBlockIds = new Set<string>()

  const sections = content.content.map((sectionNode) => {
    if (sectionNode.type !== 'resumeSection') throw new Error(`Unsupported section node: ${sectionNode.type || 'unknown'}`)
    const meta = sectionNode.attrs?.meta as Record<string, any> | undefined
    if (!meta || typeof meta.id !== 'string') throw new Error('A section is missing its stable identity.')
    const originalSection = originalSections.get(meta.id)
    if (!originalSection || meta.type !== originalSection.type || meta.required !== originalSection.required ||
      typeof meta.formatting !== 'object' || meta.formatting === null) {
      throw new Error('Section identity or required structure changed.')
    }
    const blocks = (sectionNode.content || []).map((blockNode) => {
      if (blockNode.type === 'editableSkillGroup') {
        const meta = blockNode.attrs?.meta as Record<string, any> | undefined
        const formatting = blockNode.attrs?.formatting as Record<string, any> | undefined
        const originalBlock = meta?.id ? originalBlocks.get(meta.id) : undefined
        if (!meta || !formatting || typeof formatting !== 'object' || !originalBlock || originalBlock.type !== 'skill_group' ||
          stableStringify(meta) !== stableStringify(stripKeys(originalBlock, ['items', 'formatting']))) {
          throw new Error('Skill group identity or metadata changed.')
        }
        const text = (blockNode.content || []).map((child) => String(child.text || '')).join('')
        const values = text.split(',').map((item) => item.trim()).filter(Boolean)
        const items = values.map((value, index) => {
          const originalItem = originalBlock.items?.[index]
          if (!originalItem) throw new Error('Only existing source-backed skills can be edited.')
          return { ...clone(originalItem), text: value, edit_policy: 'editable_source_backed' }
        })
        if (usedBlockIds.has(meta.id)) throw new Error('Duplicate block identity in the editor.')
        usedBlockIds.add(meta.id)
        return { ...clone(meta), formatting: clone(formatting), items, source_refs: collectSourceRefs(items) }
      }
      if (blockNode.type === 'layoutParagraph') {
        const block = blockNode.attrs?.block as ResumeBlock | undefined
        if (!block || block.type !== 'layout_paragraph' || block.edit_policy !== 'presentation' ||
          !/^blk_[a-f0-9]{16}$/.test(block.id) || !Array.isArray(block.source_refs) || block.source_refs.length ||
          !block.formatting || typeof block.formatting !== 'object' || (blockNode.content || []).length) {
          throw new Error('Malformed layout paragraph.')
        }
        if (usedBlockIds.has(block.id)) throw new Error('Duplicate block identity in the editor.')
        usedBlockIds.add(block.id)
        return clone(block)
      }
      if (blockNode.type === 'protectedFact') {
        const block = blockNode.attrs?.block as ResumeBlock | undefined
        if (!block) throw new Error('Malformed protected resume block.')
        const originalBlock = originalBlocks.get(block.id)
        if (block.type === 'skill_group') {
          if ((originalBlock && (originalBlock.type !== block.type || originalBlock.label !== block.label || originalBlock.edit_policy !== block.edit_policy)) ||
            (!originalBlock && block.edit_policy !== 'source_backed_read_only')) {
            throw new Error('Skill group identity or policy changed.')
          }
        } else if (!originalBlock || stableStringify(block) !== stableStringify(originalBlock)) {
          throw new Error('Protected or read-only resume content changed.')
        }
        if (usedBlockIds.has(block.id)) throw new Error('Duplicate block identity in the editor.')
        usedBlockIds.add(block.id)
        return clone(block)
      }
      if (blockNode.type !== 'editableFact') throw new Error(`Unsupported block node: ${blockNode.type || 'unknown'}`)
      const meta = blockNode.attrs?.meta as Record<string, any> | undefined
      const formatting = blockNode.attrs?.formatting as Record<string, any> | undefined
      if (!meta || typeof meta.id !== 'string' || !formatting || typeof formatting !== 'object') {
        throw new Error('An editable block is missing model metadata.')
      }
      const originalBlock = originalBlocks.get(meta.id)
      if (originalBlock) {
        const expectedMeta = stripKeys(originalBlock, ['runs', 'formatting'])
        if (!EDITABLE_TEXT_TYPES.has(originalBlock.type) && originalBlock.edit_policy !== 'editable_source_backed') {
          throw new Error('Unsupported edit policy for this block.')
        }
        expectedMeta.edit_policy = 'editable_source_backed'
        if (meta.type !== originalBlock.type || stableStringify(meta) !== stableStringify(expectedMeta)) {
          throw new Error('Block identity or provenance changed.')
        }
      } else if (!BULLET_TYPES.has(meta.type) || meta.edit_policy !== 'editable_source_backed' ||
        !/^blk_[a-f0-9]{16}$/.test(meta.id) || !Array.isArray(meta.source_refs)) {
        throw new Error('Only a new source-backed project/experience bullet may be added.')
      }
      if (usedBlockIds.has(meta.id)) throw new Error('Duplicate block identity in the editor.')
      usedBlockIds.add(meta.id)
      const nextFormatting = clone(formatting)
      const alignment = blockNode.attrs?.textAlign
      const alignmentWasExplicit = Object.prototype.hasOwnProperty.call(originalBlock?.formatting || {}, 'alignment')
      if (typeof alignment === 'string' && (alignmentWasExplicit || alignment !== 'left')) nextFormatting.alignment = alignment
      else if (!alignmentWasExplicit) delete nextFormatting.alignment
      return { ...clone(meta), formatting: nextFormatting, runs: inlineNodesToRuns(blockNode.content, meta.source_refs || []) }
    })
    return { ...clone(meta), blocks } as ResumeSection
  })

  const candidate: ResumeDocument = { ...clone(original), content: { sections } }
  candidate.source_references = collectSourceRefs(candidate.content)
  return candidate
}

function blockText(block: ResumeBlock | undefined): string {
  return (block?.runs || []).map((run) => run.text).join('')
}

function createEditLedger(original: ResumeDocument, candidate: ResumeDocument): EditLedgerItem[] {
  const originals = new Map(original.content.sections.flatMap((section) => section.blocks.map((block) => [block.id, block] as const)))
  const originalSections = new Map(original.content.sections.map((section) => [section.id, section] as const))
  const ledger: EditLedgerItem[] = []
  for (const section of candidate.content.sections) {
    const beforeSection = originalSections.get(section.id)
    if (beforeSection && (beforeSection.title !== section.title || stableStringify(beforeSection.formatting) !== stableStringify(section.formatting))) {
      ledger.push({ block_id: section.id, block_type: 'section_heading_or_spacing', edited: true,
        original_text: beforeSection.title || '', edited_text: section.title || '', source_refs: [],
        original_revision_id: original.revision_id, formatting_changed: stableStringify(beforeSection.formatting) !== stableStringify(section.formatting) })
    }
    for (const block of section.blocks) {
      const before = originals.get(block.id)
      if (block.type === 'skill_group') {
        const beforeItems = before?.items || []
        const afterItems = block.items || []
        if (!before || stableStringify(beforeItems) !== stableStringify(afterItems)) {
          ledger.push({ block_id: block.id, block_type: 'skill_group', edited: true,
            original_text: beforeItems.map((item: any) => item.text).join(', '),
            edited_text: afterItems.map((item: any) => item.text).join(', '),
            source_refs: clone(block.source_refs || []), original_revision_id: original.revision_id, formatting_changed: false })
        }
        continue
      }
      if (!editableTextBlock(block)) continue
      const formattingChanged = !before || stableStringify(before.formatting) !== stableStringify(block.formatting)
      const beforeRuns = stableStringify(before?.runs || [])
      const afterRuns = stableStringify(block.runs)
      if (!before || beforeRuns !== afterRuns || formattingChanged) {
        ledger.push({ block_id: block.id, block_type: block.type, edited: true,
          original_text: blockText(before), edited_text: blockText(block),
          source_refs: clone(before?.source_refs || block.source_refs || []),
          original_revision_id: original.revision_id, formatting_changed: formattingChanged })
      }
    }
  }
  for (const section of original.content.sections) {
    for (const block of section.blocks) {
      if (block.type === 'skill_group' && !candidate.content.sections.flatMap((item) => item.blocks).some((item) => item.id === block.id)) {
        ledger.push({ block_id: block.id, block_type: 'skill_group', edited: true,
          original_text: (block.items || []).map((item: any) => item.text).join(', '), edited_text: '',
          source_refs: clone(block.source_refs || []), original_revision_id: original.revision_id, formatting_changed: false })
      }
    }
  }
  return ledger
}

function canonicalLinksBySource(document: ResumeDocument): Map<string, Set<string>> {
  const links = new Map<string, Set<string>>()
  for (const section of document.content.sections) {
    for (const block of section.blocks) {
      for (const run of block.runs || []) {
        for (const mark of run.marks || []) {
          if (mark.type !== 'link' || typeof mark.href !== 'string') continue
          for (const ref of run.source_refs || []) {
            const key = `${ref.source_type}\u0000${ref.source_id}`
            if (!links.has(key)) links.set(key, new Set())
            links.get(key)!.add(mark.href)
          }
        }
      }
    }
  }
  return links
}

function safeLinkScheme(href: string): boolean {
  const scheme = href.split(':', 1)[0]?.toLowerCase()
  return ['https', 'mailto', 'tel'].includes(scheme) && !/[\u0000-\u001f\s]/.test(href)
}

export function isCanonicalResumeLink(href: string, refs: SourceRef[], document: ResumeDocument): boolean {
  if (!safeLinkScheme(href)) return false
  const links = canonicalLinksBySource(document)
  return refs.some((ref) => links.get(`${ref.source_type}\u0000${ref.source_id}`)?.has(href) === true)
}

function formattingStyle(formatting: Record<string, any>, alignment?: string): CSSProperties {
  const style: CSSProperties = {}
  if (typeof formatting.font_size_pt === 'number') style.fontSize = `${formatting.font_size_pt}pt`
  if (typeof formatting.line_spacing === 'number') style.lineHeight = String(formatting.line_spacing)
  if (typeof formatting.space_before_pt === 'number') style.marginTop = `${formatting.space_before_pt}pt`
  if (typeof formatting.space_after_pt === 'number') style.marginBottom = `${formatting.space_after_pt}pt`
  if (typeof formatting.left_indent_in === 'number') style.marginLeft = `${formatting.left_indent_in}in`
  if (typeof formatting.first_line_indent_in === 'number') style.textIndent = `${formatting.first_line_indent_in}in`
  if (formatting.bold) style.fontWeight = 700
  if (alignment || formatting.alignment) style.textAlign = (alignment || formatting.alignment) as CSSProperties['textAlign']
  return style
}

function ResumeSectionView({ node, updateAttributes }: NodeViewProps) {
  const meta = (node.attrs.meta || {}) as Record<string, any>
  return <NodeViewWrapper as="section" className="resume-document-section" data-section-type={meta.type} data-section-id={meta.id}>
    {meta.title !== null && meta.title !== undefined && <h2 className="resume-document-section-title">
      <input className="resume-section-heading-input" aria-label={`Section heading ${meta.type}`} value={String(meta.title)}
        maxLength={60} onChange={(event) => updateAttributes({ meta: { ...meta, title: event.target.value } })}
        onKeyDown={(event) => { if (event.key === 'Enter') event.preventDefault() }} />
    </h2>}
    <NodeViewContent as="div" className="resume-document-section-content" />
  </NodeViewWrapper>
}

function StaticFactView({ node }: NodeViewProps) {
  const block = (node.attrs.block || {}) as ResumeBlock
  const style = formattingStyle(block.formatting || {})
  if (block.type === 'project_tech_stack') {
    return <NodeViewWrapper as="div" className="resume-editor-protected" contentEditable={false} data-block-id={block.id} data-block-type={block.type} style={style}>
      <b style={formattingStyle(block.label_formatting || {})}>{String(block.label || '').trimEnd()}</b>{'\u00a0'}{(block.items || []).map((item: any) => item.text).join(', ')}
    </NodeViewWrapper>
  }
  return <NodeViewWrapper as="div" className={`resume-editor-protected resume-editor-protected-${block.type}`} contentEditable={false} data-block-id={block.id} data-block-type={block.type} style={style}>
    {(block.runs || []).map((run, index) => {
      let value: ReactNode = run.text
      for (const mark of run.marks || []) {
        if (mark.type === 'bold') value = <strong>{value}</strong>
        else if (mark.type === 'italic') value = <em>{value}</em>
        else if (mark.type === 'underline') value = <u>{value}</u>
        else if (mark.type === 'link') value = <a href={mark.href} target={String(mark.href).startsWith('https:') ? '_blank' : undefined} rel="noreferrer">{value}</a>
      }
      return <span key={`${block.id}-${index}`}>{value}</span>
    })}
  </NodeViewWrapper>
}

function EditableSkillGroupView({ node }: NodeViewProps) {
  const meta = (node.attrs.meta || {}) as Record<string, any>
  const formatting = (node.attrs.formatting || {}) as Record<string, any>
  return <NodeViewWrapper as="div" className="resume-editor-editable resume-editor-skill-group" contentEditable={true}
    data-testid="resume-editable-block" data-block-id={meta.id} data-block-type="skill_group" style={formattingStyle(formatting)}>
    <b className="resume-skill-label" style={formattingStyle(meta.label_formatting || {})}>{String(meta.label || '')}:{'\u00a0'}</b>
    <NodeViewContent className="resume-editor-editable-content" />
  </NodeViewWrapper>
}

function EditableFactView({ node, selected }: NodeViewProps) {
  const meta = (node.attrs.meta || {}) as Record<string, any>
  const formatting = (node.attrs.formatting || {}) as Record<string, any>
  const alignment = node.attrs.textAlign as string | undefined
  const listStyle = formatting.list_style || 'none'
  return <NodeViewWrapper as="div" className={`resume-editor-editable${selected ? ' is-selected' : ''}`} contentEditable={true}
    data-testid="resume-editable-block" data-block-id={meta.id} data-block-type={meta.type} data-list-style={listStyle}
    style={formattingStyle(formatting, alignment)}>
    <NodeViewContent className="resume-editor-editable-content" />
  </NodeViewWrapper>
}

const ResumeSectionNode = TiptapNode.create({
  name: 'resumeSection',
  group: 'block',
  content: 'resumeBlock+',
  defining: true,
  isolating: true,
  addAttributes() { return { meta: { default: {} } } },
  parseHTML() { return [{ tag: 'section[data-resume-section]' }] },
  renderHTML({ HTMLAttributes }) { return ['section', { ...HTMLAttributes, 'data-resume-section': '' }, 0] },
  addNodeView() { return ReactNodeViewRenderer(ResumeSectionView) },
})

const SourceRefsMark = Mark.create({
  name: 'sourceRefs',
  addAttributes() { return { refs: { default: [] } } },
  parseHTML() { return [] },
  renderHTML({ mark }) { return ['span', { 'data-resume-source-refs': JSON.stringify(mark.attrs.refs) }, 0] },
})

const ProtectedFactNode = TiptapNode.create({
  name: 'protectedFact',
  group: 'resumeBlock',
  atom: true,
  selectable: false,
  draggable: false,
  isolating: true,
  addAttributes() { return { block: { default: {} } } },
  parseHTML() { return [{ tag: 'div[data-resume-protected]' }] },
  renderHTML({ HTMLAttributes }) { return ['div', { ...HTMLAttributes, 'data-resume-protected': '' }] },
  addNodeView() { return ReactNodeViewRenderer(StaticFactView) },
})

const EditableSkillGroupNode = TiptapNode.create({
  name: 'editableSkillGroup',
  group: 'resumeBlock',
  content: 'inline*',
  defining: true,
  isolating: true,
  selectable: false,
  draggable: false,
  addAttributes() { return { meta: { default: {} }, formatting: { default: {} } } },
  parseHTML() { return [] },
  renderHTML({ HTMLAttributes }) { return ['div', { ...HTMLAttributes, 'data-resume-editable-skill-group': '' }, 0] },
  addNodeView() { return ReactNodeViewRenderer(EditableSkillGroupView) },
})

const LayoutParagraphNode = TiptapNode.create({
  name: 'layoutParagraph',
  group: 'resumeBlock',
  content: 'inline*',
  isolating: true,
  selectable: false,
  draggable: false,
  addAttributes() { return { block: { default: {} } } },
  parseHTML() { return [] },
  renderHTML({ HTMLAttributes }) { return ['p', { ...HTMLAttributes, 'data-resume-layout-paragraph': '' }] },
  addKeyboardShortcuts() {
    const removeEmpty = () => {
      const { state, view } = this.editor
      const { $from } = state.selection
      const depth = $from.depth > 0 && $from.node($from.depth).type.name === 'layoutParagraph' ? $from.depth : -1
      if (depth < 0 || $from.node(depth).content.size) return false
      const pos = $from.before(depth)
      view.dispatch(state.tr.delete(pos, pos + $from.node(depth).nodeSize).scrollIntoView())
      return true
    }
    return { Backspace: removeEmpty, Delete: removeEmpty }
  },
})

const EditableFactNode = TiptapNode.create({
  name: 'editableFact',
  group: 'resumeBlock',
  content: 'inline*',
  defining: true,
  isolating: true,
  selectable: false,
  draggable: false,
  addAttributes() { return { meta: { default: {} }, formatting: { default: {} } } },
  parseHTML() { return [{ tag: 'div[data-resume-editable]' }] },
  renderHTML({ HTMLAttributes }) { return ['div', { ...HTMLAttributes, 'data-resume-editable': '' }, 0] },
  addKeyboardShortcuts() {
    return {
      Enter: () => this.editor.commands.setHardBreak(),
      'Shift-Enter': () => this.editor.commands.setHardBreak(),
    }
  },
  addNodeView() { return ReactNodeViewRenderer(EditableFactView) },
})

function layoutParagraphBlock(): ResumeBlock {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return {
    id: `blk_${Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')}`,
    type: 'layout_paragraph', edit_policy: 'presentation', formatting: {}, source_refs: [],
  }
}

function insertLayoutParagraph(view: any): boolean {
  const { state } = view
  const selection = state.selection
  let insertPos = -1
  if (selection instanceof GapCursor) insertPos = selection.from
  else if (selection.empty && selection.$from.parent.type.name === 'editableFact' &&
    selection.$from.parentOffset === selection.$from.parent.content.size) {
    insertPos = selection.$from.after(selection.$from.depth)
  }
  if (insertPos < 0) return false
  const node = state.schema.nodes.layoutParagraph.create({ block: layoutParagraphBlock() })
  const transaction = state.tr.insert(insertPos, node)
  transaction.setSelection(TextSelection.create(transaction.doc, insertPos + 1))
  view.dispatch(transaction.scrollIntoView())
  return true
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const headers = new Headers(options?.headers)
  if (options?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(apiUrl(path), { ...options, headers })
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const details = [...(Array.isArray(data?.errors) ? data.errors : []), ...(Array.isArray(data?.claim_validation?.errors) ? data.claim_validation.errors : [])]
      .map((item: any) => item?.message).filter((item: any) => typeof item === 'string')
    throw new Error([data?.error || data?.message || `Request failed (${response.status})`, ...details].join(' '))
  }
  if (data === null) throw new Error('The API returned an invalid JSON response.')
  return data
}

export function ResumeDocumentEditor({ applicationId, companyName, onCancel, onSaved }: { applicationId: string; companyName: string; onCancel: () => void; onSaved: (result: { revision_id: string; page_count: number }) => void }) {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [document, setDocument] = useState<ResumeDocument | null>(null)
  useEffect(() => {
    let active = true
    requestJson<{ application_id: string; company_name: string; document: ResumeDocument }>(`/api/applications/${encodeURIComponent(applicationId)}/resume-document`)
      .then((result) => {
        if (!active) return
        if (result.document.application_id !== applicationId) throw new Error('The loaded ResumeDocument belongs to a different application.')
        setDocument(result.document)
        setLoadError('')
      })
      .catch((error: any) => { if (active) setLoadError(error.message || 'The ResumeDocument could not be loaded.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [applicationId])

  if (loading) return <div className="resume-editor-loading"><LoadingStatus label="LOADING SELECTED APPLICATION DOCUMENT…" /></div>
  if (loadError || !document) return <div className="resume-editor-load-error" role="alert"><p>{loadError || 'ResumeDocument unavailable.'}</p><button className="button quiet" onClick={onCancel}>CANCEL / BACK TO RESUME WORKSPACE</button></div>
  return <LoadedResumeDocumentEditor key={`${applicationId}-${document.revision_id}`} initialDocument={document} companyName={companyName} onCancel={onCancel} onSaved={onSaved} />
}

function LoadedResumeDocumentEditor({ initialDocument, companyName, onCancel, onSaved }: { initialDocument: ResumeDocument; companyName: string; onCancel: () => void; onSaved: (result: { revision_id: string; page_count: number }) => void }) {
  const [draftJson, setDraftJson] = useState<JSONContent>(() => modelToEditorContent(initialDocument))
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<{ kind: 'idle' | 'success' | 'error'; message: string }>({ kind: 'idle', message: '' })
  const [linkPanelOpen, setLinkPanelOpen] = useState(false)
  const [linkValue, setLinkValue] = useState('')
  const [linkError, setLinkError] = useState('')
  const [, setSelectionVersion] = useState(0)
  const canonicalLinks = useMemo(() => {
    const values = new Set<string>()
    for (const section of initialDocument.content.sections) for (const block of section.blocks) for (const run of block.runs || []) for (const mark of run.marks || []) {
      if (mark.type === 'link' && typeof mark.href === 'string') values.add(mark.href)
    }
    return values
  }, [initialDocument])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        blockquote: false, bulletList: false, code: false, codeBlock: false,
        heading: false, horizontalRule: false, listItem: false, orderedList: false,
        paragraph: false, strike: false, dropcursor: false, gapcursor: false,
        trailingNode: false, listKeymap: false,
        link: {
          autolink: false,
          linkOnPaste: false,
          openOnClick: false,
          protocols: ['mailto', { scheme: 'tel', optionalSlashes: true }],
          isAllowedUri: (href: string) => safeLinkScheme(href) && canonicalLinks.has(href),
        },
      }),
      Gapcursor,
      TextAlign.configure({ types: ['editableFact', 'editableSkillGroup'], alignments: ['left', 'center', 'right', 'justify'] }),
      SourceRefsMark,
      ResumeSectionNode,
      ProtectedFactNode,
      EditableSkillGroupNode,
      LayoutParagraphNode,
      EditableFactNode,
    ],
    content: modelToEditorContent(initialDocument),
    immediatelyRender: false,
    onUpdate: ({ editor }) => {
      setDraftJson(editor.getJSON())
      setStatus({ kind: 'idle', message: '' })
    },
    onSelectionUpdate: () => setSelectionVersion((version) => version + 1),
    editorProps: {
      attributes: { class: 'resume-document-editor-content', 'aria-label': `Resume document editor for ${companyName}` },
      handleKeyDown: (view, event) => {
        if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && insertLayoutParagraph(view)) {
          event.preventDefault()
          return true
        }
        if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return false
        const markName = ({ b: 'bold', i: 'italic', u: 'underline' } as Record<string, string>)[event.key.toLowerCase()]
        const mark = markName ? view.state.schema.marks[markName] : undefined
        if (!mark) return false
        event.preventDefault()
        const { from, to, empty, $from } = view.state.selection
        const active = empty
          ? mark.isInSet(view.state.storedMarks || $from.marks()) !== undefined
          : view.state.doc.rangeHasMark(from, to, mark)
        let transaction = view.state.tr
        if (empty) transaction = active ? transaction.removeStoredMark(mark) : transaction.addStoredMark(mark.create())
        else transaction = active ? transaction.removeMark(from, to, mark) : transaction.addMark(from, to, mark.create())
        view.dispatch(transaction.scrollIntoView())
        return true
      },
      handlePaste: (view, event) => {
        event.preventDefault()
        const text = event.clipboardData?.getData('text/plain') || ''
        const { from, to, $from, $to } = view.state.selection
        if (!text || !$from.parent.type.inlineContent || $from.parent !== $to.parent) return true
        view.dispatch(view.state.tr.insertText(text.replace(/\r\n?/g, ' ').replace(/[\u2028\u2029]/g, ' '), from, to))
        return true
      },
      handleDrop: () => true,
    },
  })

  const candidate = useMemo(() => {
    try { return editorContentToModel(draftJson, initialDocument) }
    catch { return null }
  }, [draftJson, initialDocument])
  const ledger = useMemo(() => candidate ? createEditLedger(initialDocument, candidate) : [], [candidate, initialDocument])
  const context = editableContext(editor)
  const activeSection = sectionContext(editor)
  const currentFormatting = context?.node.attrs.formatting || {}
  const currentMeta = context?.node.attrs.meta || {}
  const isBullet = ['project_bullet', 'experience_bullet'].includes(currentMeta.type)
  const canReorderEntry = ['education_line', 'certification_entry'].includes(currentMeta.type)
  const activeSectionFormatting = activeSection?.node.attrs.meta?.formatting || {}
  const selectedAllowedLinks = context ? canonicalLinksForRefs(initialDocument, currentMeta.source_refs || []) : []

  function openLinkPanel() {
    const existing = editor?.getAttributes('link')?.href || ''
    setLinkValue(existing)
    setLinkError('')
    setLinkPanelOpen(true)
  }

  function applyLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!editor || (editor.state.selection.empty && !editor.isActive('link'))) {
      setLinkError('Select text in an editable source-backed block before adding a link.')
      return
    }
    const href = linkValue.trim()
    if (!isCanonicalResumeLink(href, currentMeta.source_refs || [], initialDocument)) {
      setLinkError('Use only a canonical HTTPS, mailto, or tel link that is backed by this block’s source references.')
      return
    }
    if (!editor.chain().focus().extendMarkRange('link').setLink({ href }).run()) {
      setLinkError('The selected text could not be linked in the current block.')
      return
    }
    setLinkPanelOpen(false)
    setLinkError('')
  }

  function removeLink() {
    editor?.chain().focus().extendMarkRange('link').unsetLink().run()
    setLinkPanelOpen(false)
    setLinkError('')
  }

  function setFormatting(patch: Record<string, any>) {
    if (!editor || !context) return
    const formatting = { ...(context.node.attrs.formatting || {}), ...patch }
    editor.chain().focus().updateAttributes(context.node.type.name, { formatting }).run()
  }

  function setSectionFormatting(patch: Record<string, any>) {
    if (!editor) return
    editor.chain().focus().command(({ tr, state }) => {
      const target = sectionContextFromState(state)
      if (!target) return false
      const meta = target.node.attrs.meta || {}
      tr.setNodeMarkup(target.pos, target.node.type, {
        ...target.node.attrs,
        meta: { ...meta, formatting: { ...(meta.formatting || {}), ...patch } },
      })
      return true
    }).run()
  }

  async function saveChanges() {
    if (!editor || busy) return
    setBusy(true)
    setStatus({ kind: 'idle', message: '' })
    try {
      const currentModel = editorContentToModel(editor.getJSON(), initialDocument)
      const currentLedger = createEditLedger(initialDocument, currentModel)
      const result = await requestJson<{ decision: string; persisted: boolean; working: { revision_id: string; page_count: number }; validation: { final_status: string } }>(
        `/api/applications/${encodeURIComponent(initialDocument.application_id)}/resume-document/save`,
        { method: 'POST', body: JSON.stringify({ document: currentModel, base_revision_id: initialDocument.revision_id, edit_ledger: currentLedger }) },
      )
      if (result.decision !== 'saved' || result.persisted !== true || result.validation?.final_status !== 'PASS' || result.working?.page_count !== 1) {
        throw new Error('Save response did not confirm a persisted, passing one-page Working Resume revision.')
      }
      onSaved({ revision_id: result.working.revision_id, page_count: result.working.page_count })
    } catch (error: any) {
      setStatus({ kind: 'error', message: error.message || 'ResumeDocument validation failed.' })
    } finally {
      setBusy(false)
    }
  }

  if (!editor) return <div className="resume-editor-loading" role="status">PREPARING THE RESUME EDITOR…</div>

  return <div className="resume-document-editor" data-testid="resume-document-editor">
    <div className="resume-editor-context"><div><span className="card-label">SELECTED APPLICATION · READ-ONLY CONTEXT</span><strong>{companyName}</strong><small>Application ID: {initialDocument.application_id}</small></div><span className="pill">SCHEMA V{initialDocument.schema_version}</span></div>
    <div className="resume-editor-guardrail"><b>Source-backed editing only.</b> Factual text stays linked to canonical evidence; skill choices come from the supported catalog. Contact details, project technology lists, stable identities, and section order remain protected. SAVE WORKING validates the new revision and one-page DOCX/PDF before activation; Final Resume remains untouched. CANCEL / DISCARD writes nothing.</div>

    <div className="resume-editor-toolbar" role="toolbar" aria-label="Resume formatting tools">
      <button className="editor-tool" aria-label="Bold" aria-pressed={editor.isActive('bold')} disabled={!context} onMouseDown={(event) => event.preventDefault()} onClick={() => editor.chain().focus().toggleBold().run()}><b>B</b></button>
      <button className="editor-tool" aria-label="Italic" aria-pressed={editor.isActive('italic')} disabled={!context} onMouseDown={(event) => event.preventDefault()} onClick={() => editor.chain().focus().toggleItalic().run()}><i>I</i></button>
      <button className="editor-tool" aria-label="Underline" aria-pressed={editor.isActive('underline')} disabled={!context} onMouseDown={(event) => event.preventDefault()} onClick={() => editor.chain().focus().toggleUnderline().run()}><u>U</u></button>
      <span className="editor-tool-separator" />
      <label className="editor-select-label">FONT SIZE
        <select aria-label="Font size preset" value={String(currentFormatting.font_size_pt ?? 11)} disabled={!context} onChange={(event) => setFormatting({ font_size_pt: Number(event.target.value) })}>
          {FONT_SIZES.map((size) => <option key={size} value={size}>{size} pt</option>)}
        </select>
      </label>
      <label className="editor-select-label">LINE SPACING
        <select aria-label="Line spacing preset" value={String(currentFormatting.line_spacing ?? 1)} disabled={!context} onChange={(event) => setFormatting({ line_spacing: Number(event.target.value) })}>
          {LINE_SPACINGS.map((spacing) => <option key={spacing} value={spacing}>{spacing.toFixed(2)}×</option>)}
        </select>
      </label>
      <label className="editor-select-label">{currentMeta.type === 'project_entry' ? 'PROJECT BEFORE' : 'BLOCK BEFORE'}
        <select aria-label="Block spacing before" value={String(currentFormatting.space_before_pt ?? 0)} disabled={!context} onMouseDown={(event) => event.preventDefault()} onChange={(event) => setFormatting({ space_before_pt: Number(event.target.value) })}>
          {[...new Set([...SPACING_PRESETS, ...(typeof currentFormatting.space_before_pt === 'number' ? [currentFormatting.space_before_pt] : [])])].sort((a, b) => a - b).map((value) => <option key={value} value={value}>{value} pt</option>)}
        </select>
      </label>
      <label className="editor-select-label">{currentMeta.type === 'project_entry' ? 'TITLE → BULLETS' : currentMeta.type === 'project_bullet' ? 'BULLET AFTER' : 'BLOCK AFTER'}
        <select aria-label="Block spacing after" value={String(currentFormatting.space_after_pt ?? 0)} disabled={!context} onMouseDown={(event) => event.preventDefault()} onChange={(event) => setFormatting({ space_after_pt: Number(event.target.value) })}>
          {[...new Set([...SPACING_PRESETS, ...(typeof currentFormatting.space_after_pt === 'number' ? [currentFormatting.space_after_pt] : [])])].sort((a, b) => a - b).map((value) => <option key={value} value={value}>{value} pt</option>)}
        </select>
      </label>
      <label className="editor-select-label">SECTION BEFORE
        <select aria-label="Section spacing before" value={String(activeSectionFormatting.space_before_pt ?? 0)} disabled={!activeSection} onMouseDown={(event) => event.preventDefault()} onChange={(event) => setSectionFormatting({ space_before_pt: Number(event.target.value) })}>
          {[...new Set([...SPACING_PRESETS, ...(typeof activeSectionFormatting.space_before_pt === 'number' ? [activeSectionFormatting.space_before_pt] : [])])].sort((a, b) => a - b).map((value) => <option key={value} value={value}>{value} pt</option>)}
        </select>
      </label>
      <label className="editor-select-label">SECTION AFTER
        <select aria-label="Section spacing after" value={String(activeSectionFormatting.space_after_pt ?? 0)} disabled={!activeSection} onMouseDown={(event) => event.preventDefault()} onChange={(event) => setSectionFormatting({ space_after_pt: Number(event.target.value) })}>
          {[...new Set([...SPACING_PRESETS, ...(typeof activeSectionFormatting.space_after_pt === 'number' ? [activeSectionFormatting.space_after_pt] : [])])].sort((a, b) => a - b).map((value) => <option key={value} value={value}>{value} pt</option>)}
        </select>
      </label>
      <span className="editor-tool-separator" />
      {ALIGNMENTS.map((alignment) => <button key={alignment} className={`editor-tool${(context?.node.attrs.textAlign || currentFormatting.alignment || 'left') === alignment ? ' active' : ''}`} aria-label={`Align ${alignment}`} disabled={!context} onMouseDown={(event) => event.preventDefault()} onClick={() => editor.chain().focus().setTextAlign(alignment).run()}>{alignment === 'left' ? 'L' : alignment === 'center' ? 'C' : 'R'}</button>)}
      <button className={`editor-tool${currentFormatting.list_style === 'bullet' ? ' active' : ''}`} aria-label="Bullet list" aria-pressed={currentFormatting.list_style === 'bullet'} disabled={!context} onMouseDown={(event) => event.preventDefault()} onClick={() => setFormatting({ list_style: currentFormatting.list_style === 'bullet' ? 'none' : 'bullet' })}>• List</button>
      <button className={`editor-tool${currentFormatting.list_style === 'ordered' ? ' active' : ''}`} aria-label="Numbered list" aria-pressed={currentFormatting.list_style === 'ordered'} disabled={!context} onMouseDown={(event) => event.preventDefault()} onClick={() => setFormatting({ list_style: currentFormatting.list_style === 'ordered' ? 'none' : 'ordered' })}>1. List</button>
      <button className="editor-tool" aria-label="Add or edit canonical link" disabled={!context} onMouseDown={(event) => event.preventDefault()} onClick={openLinkPanel}>LINK</button>
      <button className="editor-tool" aria-label="Undo" disabled={!editor.can().undo()} onMouseDown={(event) => event.preventDefault()} onClick={() => editor.chain().focus().undo().run()}>UNDO</button>
      <button className="editor-tool" aria-label="Redo" disabled={!editor.can().redo()} onMouseDown={(event) => event.preventDefault()} onClick={() => editor.chain().focus().redo().run()}>REDO</button>
    </div>

    {linkPanelOpen && <form className="resume-link-panel" onSubmit={applyLink}>
      <label>CANONICAL LINK FOR THIS SOURCE
        <input type="text" list="resume-canonical-links" value={linkValue} onChange={(event) => setLinkValue(event.target.value)} placeholder="https://… · mailto:… · tel:…" aria-label="Canonical link URL" />
        <datalist id="resume-canonical-links">{selectedAllowedLinks.map((href) => <option key={href} value={href} />)}</datalist>
      </label>
      {linkError && <span className="resume-editor-inline-error" role="alert">{linkError}</span>}
      <div><button className="button primary" type="submit">APPLY LINK</button>{editor.isActive('link') && <button className="button quiet" type="button" onClick={removeLink}>REMOVE LINK</button>}<button className="button quiet" type="button" onClick={() => { setLinkPanelOpen(false); setLinkError('') }}>CANCEL</button></div>
    </form>}

    {isBullet && <div className="resume-bullet-controls" aria-label="Supported bullet actions">
      <span>Source-backed bullet actions</span>
      <button className="button quiet" onClick={() => moveCurrentBullet(editor, -1)} disabled={!canMoveCurrentBullet(editor, -1)}>MOVE UP</button>
      <button className="button quiet" onClick={() => moveCurrentBullet(editor, 1)} disabled={!canMoveCurrentBullet(editor, 1)}>MOVE DOWN</button>
      <button className="button quiet" onClick={() => addCurrentBullet(editor)} disabled={!canAddCurrentBullet(editor)}>ADD SUPPORTED BULLET</button>
      <button className="button quiet" onClick={() => removeCurrentBullet(editor)}>REMOVE BULLET FROM THIS SESSION</button>
      <small>New bullets retain the selected project/experience source; the server rejects wording outside the cited evidence. Five bullets maximum per entry.</small>
    </div>}

    {canReorderEntry && <div className="resume-bullet-controls" aria-label="Record reordering actions">
      <span>{currentMeta.type === 'education_line' ? 'Education record order' : 'Certification order'}</span>
      <button className="button quiet" onClick={() => moveCurrentRecord(editor, -1)} disabled={!canMoveCurrentRecord(editor, -1)}>MOVE ENTRY UP</button>
      <button className="button quiet" onClick={() => moveCurrentRecord(editor, 1)} disabled={!canMoveCurrentRecord(editor, 1)}>MOVE ENTRY DOWN</button>
      <small>Education lines move together as one record; certification entries move as complete source-backed records.</small>
    </div>}

    <div className="resume-document-canvas"><EditorContent editor={editor} /></div>

    <div className="resume-editor-revision-ledger" aria-label="Edited source-backed blocks">
      <div><span className="card-label">SESSION EDIT LEDGER</span><b>{ledger.length} block{ledger.length === 1 ? '' : 's'} edited</b><small>Original source references and edited text remain available together for future validation.</small></div>
      {ledger.length === 0 ? <p>No source-backed text or formatting changes yet.</p> : <div className="resume-ledger-list">{ledger.map((item) => <details key={item.block_id}>
        <summary><b>EDITED</b> {item.block_type} · {item.block_id}</summary>
        <small>Source: {item.source_refs.map((ref) => `${ref.source_type}:${ref.source_id}`).join(' · ')}</small>
        <p><strong>Original:</strong> {item.original_text}</p><p><strong>Current:</strong> {item.edited_text}</p>
      </details>)}</div>}
    </div>

    {!busy && ledger.length > 0 && <div className="resume-save-status unsaved" role="status">● UNSAVED CHANGES</div>}
    {status.message && <div className={`resume-editor-result ${status.kind}`} role={status.kind === 'error' ? 'alert' : 'status'} data-testid="resume-validation-result">{status.message}</div>}
    <div className="resume-editor-footer"><span>Validation and staged DOCX/PDF generation run before the active Working references, hashes, and revision metadata change. The Final Resume is not modified.</span><div>
      <button className="button quiet" onClick={onCancel} disabled={busy}>CANCEL / DISCARD</button>
      <button className="button primary" data-testid="save-resume-document" onClick={saveChanges} disabled={busy || !candidate}>{busy ? <LoadingStatus label="SAVING..." /> : 'SAVE WORKING'}</button>
    </div></div>
  </div>
}

function canonicalLinksForRefs(document: ResumeDocument, refs: SourceRef[]): string[] {
  const links = canonicalLinksBySource(document)
  const values = new Set<string>()
  for (const ref of refs) for (const href of links.get(`${ref.source_type}\u0000${ref.source_id}`) || []) values.add(href)
  return [...values].sort()
}

function editableContextFromState(state: any) {
  const $from = state.selection.$from
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const node = $from.node(depth)
    if (!['editableFact', 'editableSkillGroup'].includes(node.type.name)) continue
    const parentDepth = depth - 1
    const parent = $from.node(parentDepth)
    const nodePos = $from.before(depth)
    const parentStart = $from.start(parentDepth)
    let index = 0
    let position = parentStart
    while (index < parent.childCount && position < nodePos) {
      position += parent.child(index).nodeSize
      index += 1
    }
    if (index >= parent.childCount) return null
    return { node, parent, parentStart, index, pos: position }
  }
  return null
}

function editableContext(editor: TiptapEditor | null) {
  return editor ? editableContextFromState(editor.state) : null
}

function isSameBulletGroup(first: any, second: any): boolean {
  if (!first || !second || first.type.name !== 'editableFact' || second.type.name !== 'editableFact') return false
  const a = first.attrs.meta || {}
  const b = second.attrs.meta || {}
  if (a.type !== b.type || !['project_bullet', 'experience_bullet'].includes(a.type)) return false
  const groupingKey = a.type === 'project_bullet' ? 'project_id' : 'experience_id'
  return Boolean(a[groupingKey] && a[groupingKey] === b[groupingKey])
}

function canMoveCurrentBullet(editor: TiptapEditor, direction: -1 | 1): boolean {
  const context = editableContext(editor)
  if (!context) return false
  const targetIndex = context.index + direction
  if (targetIndex < 0 || targetIndex >= context.parent.childCount) return false
  return isSameBulletGroup(context.node, context.parent.child(targetIndex))
}

function moveCurrentBullet(editor: TiptapEditor, direction: -1 | 1) {
  editor.chain().focus().command(({ tr, state }) => {
    const context = editableContextFromState(state)
    if (!context) return false
    const targetIndex = context.index + direction
    if (targetIndex < 0 || targetIndex >= context.parent.childCount) return false
    const sibling = context.parent.child(targetIndex)
    if (!isSameBulletGroup(context.node, sibling)) return false
    let siblingPos = context.parentStart
    for (let index = 0; index < targetIndex; index += 1) siblingPos += context.parent.child(index).nodeSize
    const firstPos = direction < 0 ? siblingPos : context.pos
    const first = direction < 0 ? sibling : context.node
    const second = direction < 0 ? context.node : sibling
    tr.replaceWith(firstPos, firstPos + first.nodeSize + second.nodeSize, PMFragment.fromArray([second, first]))
    return true
  }).run()
}

function removeCurrentBullet(editor: TiptapEditor) {
  editor.chain().focus().command(({ tr, state }) => {
    const context = editableContextFromState(state)
    const type = context?.node.attrs.meta?.type
    if (!context || !['project_bullet', 'experience_bullet'].includes(type)) return false
    tr.delete(context.pos, context.pos + context.node.nodeSize)
    return true
  }).run()
}

function canAddCurrentBullet(editor: TiptapEditor): boolean {
  const context = editableContext(editor)
  if (!context || !BULLET_TYPES.has(context.node.attrs.meta?.type)) return false
  const group = Array.from({ length: context.parent.childCount }, (_, index) => context.parent.child(index))
    .filter((node: any) => isSameBulletGroup(context.node, node))
  const used = new Set(group.map((node: any) => node.attrs.meta?.bullet_index))
  return group.length < 5 && [0, 1, 2, 3, 4].some((index) => !used.has(index))
}

function addCurrentBullet(editor: TiptapEditor) {
  editor.chain().focus().command(({ tr, state }) => {
    const context = editableContextFromState(state)
    if (!context) return false
    const meta = context.node.attrs.meta || {}
    if (!BULLET_TYPES.has(meta.type)) return false
    const groupNodes = Array.from({ length: context.parent.childCount }, (_, index) => ({ index, node: context.parent.child(index) }))
      .filter(({ node }: any) => isSameBulletGroup(context.node, node))
    const used = new Set(groupNodes.map(({ node }: any) => node.attrs.meta?.bullet_index))
    const bulletIndex = [0, 1, 2, 3, 4].find((index) => !used.has(index))
    if (groupNodes.length >= 5 || bulletIndex === undefined) return false
    const bytes = new Uint8Array(8)
    globalThis.crypto.getRandomValues(bytes)
    const id = `blk_${Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')}`
    const nextMeta = { ...clone(meta), id, bullet_index: bulletIndex, edit_policy: 'editable_source_backed' }
    const formatting = { ...(context.node.attrs.formatting || {}), list_style: 'bullet' }
    const newNode = editor.schema.nodes.editableFact.create({ meta: nextMeta, formatting, textAlign: null }, [])
    const lastGroupIndex = Math.max(...groupNodes.map(({ index }: any) => index))
    const insertIndex = lastGroupIndex + 1
    let insertPos = context.parentStart
    for (let index = 0; index < insertIndex; index += 1) insertPos += context.parent.child(index).nodeSize
    tr.insert(insertPos, newNode)
    tr.setSelection(TextSelection.near(tr.doc.resolve(insertPos + 1), 1))
    return true
  }).run()
}

function sectionContextFromState(state: any) {
  const $from = state.selection.$from
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const node = $from.node(depth)
    if (node.type.name === 'resumeSection') return { node, pos: $from.before(depth) }
  }
  return null
}

function sectionContext(editor: TiptapEditor | null) {
  return editor ? sectionContextFromState(editor.state) : null
}

function recordGroupRange(parent: any, index: number) {
  const current = parent.child(index)
  const type = current.type.name === 'editableFact' ? current.attrs.meta?.type : null
  if (!['education_line', 'certification_entry'].includes(type)) return null
  const key = type === 'education_line' ? 'education_id' : 'certification_id'
  const identity = current.attrs.meta?.[key]
  const same = (node: any) => node.type.name === 'editableFact' && node.attrs.meta?.type === type && node.attrs.meta?.[key] === identity
  let first = index
  let end = index + 1
  while (first > 0 && same(parent.child(first - 1))) first -= 1
  while (end < parent.childCount && same(parent.child(end))) end += 1
  return { first, end, type, same }
}

function canMoveCurrentRecord(editor: TiptapEditor, direction: -1 | 1): boolean {
  const context = editableContext(editor)
  if (!context) return false
  const range = recordGroupRange(context.parent, context.index)
  if (!range) return false
  const targetIndex = direction < 0 ? range.first - 1 : range.end
  if (targetIndex < 0 || targetIndex >= context.parent.childCount) return false
  const adjacent = context.parent.child(targetIndex)
  return adjacent.type.name === 'editableFact' && adjacent.attrs.meta?.type === range.type
}

function moveCurrentRecord(editor: TiptapEditor, direction: -1 | 1) {
  editor.chain().focus().command(({ tr, state }) => {
    const context = editableContextFromState(state)
    if (!context) return false
    const current = recordGroupRange(context.parent, context.index)
    if (!current) return false
    const adjacentIndex = direction < 0 ? current.first - 1 : current.end
    if (adjacentIndex < 0 || adjacentIndex >= context.parent.childCount) return false
    const adjacent = recordGroupRange(context.parent, adjacentIndex)
    if (!adjacent || adjacent.type !== current.type) return false
    const firstIndex = Math.min(current.first, adjacent.first)
    const endIndex = Math.max(current.end, adjacent.end)
    const before = Array.from({ length: endIndex - firstIndex }, (_, offset) => context.parent.child(firstIndex + offset))
    const currentNodes = Array.from({ length: current.end - current.first }, (_, offset) => context.parent.child(current.first + offset))
    const adjacentNodes = Array.from({ length: adjacent.end - adjacent.first }, (_, offset) => context.parent.child(adjacent.first + offset))
    const replacement = direction < 0 ? [...currentNodes, ...adjacentNodes] : [...adjacentNodes, ...currentNodes]
    let startPos = context.parentStart
    for (let index = 0; index < firstIndex; index += 1) startPos += context.parent.child(index).nodeSize
    const totalSize = before.reduce((sum, node) => sum + node.nodeSize, 0)
    tr.replaceWith(startPos, startPos + totalSize, PMFragment.fromArray(replacement))
    return true
  }).run()
}
