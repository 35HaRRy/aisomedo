package com.dojo.aisomedo.editor

import com.dojo.aisomedo.api.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

@Serializable data class RangeInput(val start: String, val end: String)
enum class EditorIssue { READ, CONFLICT, INVALID, LIMIT, UNCERTAIN }

data class MediaEditorState(
    val snapshot: ActiveEditorOut? = null,
    val inputs: Map<String, List<RangeInput>> = emptyMap(),
    val baseInputs: Map<String, List<RangeInput>> = emptyMap(),
    val baseFolder: String? = null,
    val readRequired: Boolean = false,
    val issue: EditorIssue? = null,
    val storedDraft: StoredDraft? = null,
    val draftPackageId: Int? = null,
    val conflicts: Map<String, JsonObject> = emptyMap(),
    val persistenceIssue: DraftIssue? = null,
    val persisting: Boolean = false,
) {
    val dirty: Boolean get() = inputs != baseInputs
    val selections: Map<String, List<VideoRangeOut>>? get() {
        val result = mutableMapOf<String, List<VideoRangeOut>>()
        for (media in snapshot?.media.orEmpty().filter { it.status == "finalized" && it.isVideo }) {
            val rows = inputs[media.mediaId].orEmpty()
            if (rows.isEmpty()) continue // Omission means whole-video playback, never an empty selection.
            result[media.mediaId] = parseRanges(rows, media.sourceDuration) ?: return null
        }
        return result
    }
    val proposedTotal: Double? get() {
        val current = snapshot ?: return null
        val ranges = selections ?: return null
        var total = current.montage.cardDuration
        for (id in current.montage.order) {
            val media = current.media.find { it.mediaId == id && it.status == "finalized" } ?: return null
            total += if (media.isVideo) {
                val duration = media.sourceDuration?.takeIf { it.isFinite() && it > 0 } ?: return null
                ranges[id]?.sumOf { it.end - it.start } ?: duration
            } else photoSeconds(inputs[id]?.firstOrNull()?.end) ?: return null
        }
        return total.takeIf { it.isFinite() }
    }
    val canSave: Boolean get() = dirty && !readRequired && conflicts.isEmpty() && persistenceIssue == null && baseFolder == snapshot?.`package`?.folderName &&
        snapshot?.`package`?.status != "completed" && inputs.keys.all { id -> snapshot?.media?.any { it.mediaId == id && it.status == "finalized" } == true } &&
        proposedTotal?.let { it <= snapshot!!.montage.maxDurationSeconds } == true

    fun edit(id: String, rows: List<RangeInput>): MediaEditorState {
        val next = copy(inputs = inputs + (id to rows), issue = null)
        return next.copy(storedDraft = next.toDraft())
    }
    fun isDirty(id: String): Boolean = inputs[id].orEmpty() != baseInputs[id].orEmpty()
    fun canSave(id: String): Boolean {
        val current = snapshot ?: return false
        if (!isDirty(id) || current.media.none { it.mediaId == id && it.status == "finalized" }) return false
        val fresh = savedInputs(current)
        return copy(inputs = fresh + (id to inputs[id].orEmpty()), baseInputs = fresh).canSave
    }
    fun editPhotoDuration(id: String, value: String): MediaEditorState = edit(id, listOf(RangeInput("0", value)))
    fun discard(id: String): MediaEditorState {
        val current = snapshot ?: return this
        if (draftPackageId != null && draftPackageId != current.`package`.id || baseFolder != current.`package`.folderName) return this
        val fresh = savedInputs(current)[id].orEmpty()
        val groups = storedDraft?.groups.orEmpty() - "video:$id" - "photo:$id"
        val remaining = conflicts - "video:$id" - "photo:$id"
        val next = copy(inputs = inputs + (id to fresh), baseInputs = baseInputs + (id to fresh),
            conflicts = remaining, storedDraft = storedDraft?.copy(groups = groups, pendingRemovals = storedDraft.pendingRemovals - id),
            readRequired = readRequired && (issue != EditorIssue.CONFLICT || remaining.isNotEmpty()),
            issue = if (issue == EditorIssue.CONFLICT && remaining.isEmpty()) null else issue)
        return next.copy(storedDraft = next.toDraft())
    }
    private fun toDraft(): StoredDraft? {
        val current = snapshot ?: return storedDraft
        val groups = storedDraft?.groups.orEmpty().toMutableMap()
        val edited = mutableMapOf<String, List<RangeInput>>()
        for ((id, rows) in inputs) {
            val media = current.media.find { it.mediaId == id }
            if (media == null) { if (id in storedDraft?.inputs.orEmpty()) edited[id] = rows; continue }
            val key = "${if (media.isVideo) "video" else "photo"}:$id"
            if (rows == baseInputs[id]) { groups.remove(key); continue }
            val base = groups[key]?.base ?: if (media.isVideo) rangesGroup(baseInputs[id].orEmpty()) else photoGroup(baseInputs[id]?.firstOrNull()?.end.orEmpty())
            groups[key] = DraftGroup(base, if (media.isVideo) rangesGroup(rows) else photoGroup(rows.firstOrNull()?.end.orEmpty())); edited[id] = rows
        }
        if (groups.isEmpty() && storedDraft?.uncertain != true && storedDraft?.pendingRemovals.isNullOrEmpty()) return null
        return StoredDraft(localRevision = storedDraft?.localRevision ?: 0, folderName = storedDraft?.folderName ?: current.`package`.folderName,
            baseContentRevision = storedDraft?.baseContentRevision ?: current.contentRevision,
            groups = groups, inputs = edited, uncertain = storedDraft?.uncertain ?: false,
            pendingRemovals = storedDraft?.pendingRemovals.orEmpty())
    }
    fun restore(packageId: Int, draft: StoredDraft): MediaEditorState = copy(storedDraft = draft, draftPackageId = packageId,
        inputs = inputs + draft.inputs, baseInputs = baseInputs + draftBaselines(draft), baseFolder = draft.folderName,
        readRequired = true)
    fun discard(): MediaEditorState = snapshot?.let {
        MediaEditorState().accept(it).copy(readRequired = readRequired && this.issue == EditorIssue.UNCERTAIN,
            issue = if (this.issue == EditorIssue.UNCERTAIN) this.issue else null,
            storedDraft = storedDraft?.takeIf { draft -> draft.uncertain }?.copy(groups = emptyMap(), inputs = emptyMap(), pendingRemovals = emptySet()))
    } ?: MediaEditorState()

    fun accept(next: ActiveEditorOut, explicit: Boolean = false, expected: ActiveEditorOut? = null, savedTrims: Boolean = false): MediaEditorState {
        val fresh = savedInputs(next)
        var draft = toDraft()
        val otherPackage = draft != null && (draft.folderName != next.`package`.folderName ||
            (draftPackageId ?: snapshot?.`package`?.id) != next.`package`.id || next.`package`.status != "active")
        val conflicts = mutableMapOf<String, JsonObject>()
        if (draft != null && !otherPackage) {
            val groups = draft.groups.toMutableMap(); val retained = draft.inputs.toMutableMap()
            val removed = draft.pendingRemovals.filter { id -> next.media.any { it.mediaId == id && it.status == "removed" } }.toSet()
            for (id in removed) { groups.remove("video:$id"); groups.remove("photo:$id"); retained.remove(id) }
            for ((key, group) in groups.toMap()) {
                val current = serverGroup(next, key)
                if (current == group.proposed) { groups.remove(key); retained.remove(key.substringAfter(':')) }
                else if (current != group.base) conflicts[key] = current
            }
            val uncertain = draft.uncertain && !explicit && expected == null && groups.isNotEmpty()
            val pending = draft.pendingRemovals - removed
            draft = if (groups.isNotEmpty() || uncertain || pending.isNotEmpty()) draft.copy(groups = groups, inputs = retained, uncertain = uncertain, pendingRemovals = pending) else null
        }
        val blocked = otherPackage || conflicts.isNotEmpty() || !explicit && expected == null && issue == EditorIssue.UNCERTAIN
        return copy(snapshot = next, storedDraft = draft, draftPackageId = if (draft != null) draftPackageId ?: snapshot?.`package`?.id ?: next.`package`.id else null,
            inputs = fresh + draft?.inputs.orEmpty(), baseInputs = fresh + (draft?.let(::draftBaselines).orEmpty()),
            baseFolder = draft?.folderName ?: next.`package`.folderName, conflicts = conflicts,
            readRequired = blocked, issue = if (blocked) if (issue == EditorIssue.UNCERTAIN && conflicts.isEmpty()) issue else EditorIssue.CONFLICT else null)
    }

    fun resolveConflict(key: String, local: Boolean): MediaEditorState {
        val draft = storedDraft ?: return this
        val server = conflicts[key] ?: return this
        if (local && "status" in server) return this
        val groups = draft.groups.toMutableMap(); val retained = draft.inputs.toMutableMap()
        if (local) groups[key] = groups.getValue(key).copy(base = server)
        else { groups.remove(key); retained.remove(key.substringAfter(':')) }
        val remaining = conflicts - key
        val resolved = draft.copy(groups = groups, inputs = retained, baseContentRevision = snapshot!!.contentRevision, uncertain = false)
        val fresh = MediaEditorState().accept(snapshot!!)
        return copy(storedDraft = resolved.takeIf { groups.isNotEmpty() }, inputs = fresh.inputs + retained,
            baseInputs = fresh.baseInputs + draftBaselines(resolved), conflicts = remaining,
            readRequired = remaining.isNotEmpty(), issue = if (remaining.isEmpty()) null else EditorIssue.CONFLICT)
    }
}

private fun rangesGroup(rows: List<RangeInput>) = buildJsonObject {
    put("ranges", buildJsonArray { for (row in rows) add(buildJsonObject {
        fun value(text: String): JsonPrimitive = text.trim().replace(',', '.').toDoubleOrNull()?.takeIf { it.isFinite() }?.let(::JsonPrimitive) ?: JsonPrimitive(text)
        put("start", value(row.start)); put("end", value(row.end))
    }) })
}
private fun photoSeconds(value: String?): Double? = value?.trim()?.replace(',', '.')?.toDoubleOrNull()?.takeIf { it.isFinite() && it >= 0.04 }
private fun photoGroup(value: String) = buildJsonObject { put("seconds", photoSeconds(value)?.let(::JsonPrimitive) ?: JsonPrimitive(value)) }
private fun savedInputs(snapshot: ActiveEditorOut) = snapshot.media.filter { it.status == "finalized" }.associate { media ->
    media.mediaId to if (media.isVideo) snapshot.montage.selections[media.mediaId].orEmpty().map { RangeInput(it.start.toString(), it.end.toString()) }
        else listOf(RangeInput("0", media.effectiveDuration?.toString().orEmpty()))
}
private fun draftBaselines(draft: StoredDraft): Map<String, List<RangeInput>> = draft.groups.filterKeys { it.startsWith("video:") || it.startsWith("photo:") }
    .entries.associate { (key, group) -> key.substringAfter(':') to if (key.startsWith("photo:")) listOf(RangeInput("0", group.base.getValue("seconds").jsonPrimitive.content))
        else group.base.getValue("ranges").jsonArray.map { row -> RangeInput(row.jsonObject.getValue("start").jsonPrimitive.content, row.jsonObject.getValue("end").jsonPrimitive.content) } }
private fun serverGroup(snapshot: ActiveEditorOut, key: String): JsonObject {
    val id = key.substringAfter(':')
    val media = snapshot.media.find { it.mediaId == id && it.status == "finalized" } ?: return buildJsonObject { put("status", "unavailable") }
    if (!media.isVideo && key.startsWith("photo:")) return photoGroup(media.effectiveDuration?.toString().orEmpty())
    if (!media.isVideo || !key.startsWith("video:")) return buildJsonObject { put("status", "unavailable") }
    return rangesGroup(snapshot.montage.selections[id].orEmpty().map { RangeInput(it.start.toString(), it.end.toString()) })
}

fun parseRanges(rows: List<RangeInput>, duration: Double?): List<VideoRangeOut>? {
    if (duration == null || !duration.isFinite() || duration <= 0) return null
    val ranges = rows.map { row ->
        val start = row.start.trim().replace(',', '.').toDoubleOrNull() ?: return null
        val end = row.end.trim().replace(',', '.').toDoubleOrNull() ?: return null
        if (!start.isFinite() || !end.isFinite() || start < 0 || start >= end || end > duration || end - start + 1e-9 < 0.04) return null
        VideoRangeOut(start = start, end = end)
    }.sortedBy { it.start }
    if (ranges.zipWithNext().any { (left, right) -> left.end > right.start }) return null
    return ranges
}

fun moveMedia(order: List<String>, from: String, target: String, after: Boolean): List<String> {
    if (from == target || from !in order || target !in order) return order
    return order.toMutableList().apply { remove(from); add(indexOf(target) + if (after) 1 else 0, from) }
}
