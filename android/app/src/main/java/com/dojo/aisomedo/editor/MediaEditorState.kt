package com.dojo.aisomedo.editor

import com.dojo.aisomedo.api.*

data class RangeInput(val start: String, val end: String)
enum class EditorIssue { READ, CONFLICT, INVALID, LIMIT, UNCERTAIN }

data class MediaEditorState(
    val snapshot: ActiveEditorOut? = null,
    val inputs: Map<String, List<RangeInput>> = emptyMap(),
    val baseInputs: Map<String, List<RangeInput>> = emptyMap(),
    val baseFolder: String? = null,
    val readRequired: Boolean = false,
    val issue: EditorIssue? = null,
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
            } else media.effectiveDuration ?: return null
        }
        return total.takeIf { it.isFinite() }
    }
    val canSave: Boolean get() = dirty && !readRequired && baseFolder == snapshot?.`package`?.folderName &&
        snapshot?.`package`?.status != "completed" && inputs.keys.all { id -> snapshot?.media?.any { it.mediaId == id && it.status == "finalized" && it.isVideo } == true } &&
        proposedTotal?.let { it <= snapshot!!.montage.maxDurationSeconds } == true

    fun edit(id: String, rows: List<RangeInput>): MediaEditorState = copy(inputs = inputs + (id to rows), issue = null)
    fun discard(): MediaEditorState = snapshot?.let {
        MediaEditorState().accept(it).copy(readRequired = readRequired, issue = if (readRequired) issue else null)
    } ?: MediaEditorState()

    fun accept(next: ActiveEditorOut, explicit: Boolean = false, expected: ActiveEditorOut? = null, savedTrims: Boolean = false): MediaEditorState {
        val fresh = next.media.filter { it.isVideo && it.status == "finalized" }.associate { media ->
            media.mediaId to next.montage.selections[media.mediaId].orEmpty().map { RangeInput(it.start.toString(), it.end.toString()) }
        }
        val otherPackage = baseFolder != null && (baseFolder != next.`package`.folderName || snapshot?.`package`?.id != next.`package`.id)
        val verifiedSave = savedTrims && expected != null && !otherPackage && fingerprint(expected) == fingerprint(next)
        val keepDraft = dirty && !verifiedSave
        val changed = keepDraft && snapshot != null && fingerprint(expected ?: snapshot) != fingerprint(next)
        val blocked = keepDraft && otherPackage || expected != null && changed || !explicit && (readRequired || changed)
        val retained = if (keepDraft) inputs.filter { (id, rows) -> rows != baseInputs[id] } else emptyMap()
        return copy(snapshot = next, inputs = fresh + retained,
            baseInputs = if (keepDraft && otherPackage) baseInputs else fresh,
            baseFolder = if (keepDraft && otherPackage) baseFolder else next.`package`.folderName,
            readRequired = blocked, issue = if (blocked) EditorIssue.CONFLICT else null)
    }
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

private fun fingerprint(snapshot: ActiveEditorOut): List<Any?> = listOf(
    snapshot.`package`.id, snapshot.`package`.folderName, snapshot.`package`.status,
    snapshot.montage.order, snapshot.montage.selections, snapshot.montage.cardDuration, snapshot.montage.maxDurationSeconds,
    snapshot.media.map { listOf(it.mediaId, it.status, it.sourceDuration, if (it.isVideo) null else it.effectiveDuration) },
)

fun moveMedia(order: List<String>, from: String, target: String, after: Boolean): List<String> {
    if (from == target || from !in order || target !in order) return order
    return order.toMutableList().apply { remove(from); add(indexOf(target) + if (after) 1 else 0, from) }
}
