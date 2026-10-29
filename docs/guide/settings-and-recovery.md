# Settings and safe recovery

[README](../../README.md) · [First setup](getting-started.md) · [Publishing flow](publishing-a-reel.md)

These instructions use the web application. Read the displayed error before retrying. If a request may have reached the server, refresh its current state first.

## Settings

Open **Ayarlar** to edit Instagram connection, the publication plan, logo, caption template, opening/closing cards, and reminders. Once setup is complete, settings edits use those sections directly. Required first-run setup is not a promotional tour and cannot be skipped with **Tüm tanıtımları geç**.

Keep a test plan disabled. A valid disabled plan counts as configured but does not enable recurring preparation. Changing a one-off **Yayın Zamanı** does not rewrite the regular **Yayın Planı**. The regular plan runs every other Monday.

Branding defaults apply through the publication lifecycle; they do not silently replace the immutable video/caption already bound to a review. After relevant package edits, save and create a current render/review.

Set reminder interval and delivery-window hours under **Hatırlatmalar**. A delivery window controls when supported notifications may be sent; it is not the publication schedule. Device permissions and server push configuration are separate prerequisites.

## Upload and filename problems

- **Interrupted transfer:** check connectivity, then use **Devam et** or the displayed retry action. After refresh, choose the same original file when asked. Already accepted chunks are reconciled rather than blindly restarted.
- **Queued/processing:** wait for validation. Only **Pakete eklendi** means the file is accepted into the package.
- **Rejected file:** read the reason, correct the source, and start a new upload. Renaming a file does not change its actual format.
- **Capacity exceeded:** use smaller supported media or reduce package content. Follow the limits returned by your installation.
- **Filename conflict:** preview the existing file and choose which version to keep. **İkisini de koru** gives the new file a numbered name. Replacing the existing file needs explicit acknowledgement and permanently removes it after the replacement validates.
- **Apply to all:** this covers only the currently matching filename conflicts in the active package, not every future upload.

## Unsaved edits and stale previews

![Video section editor](../../web/public/promotion/web/sections.png)

Use the timeline to select what stays. No selection means the full video. Invalid ranges, unknown durations, or an excessive total block saving until corrected.

If another client changes the package, local drafts stay visible but may need reconciliation. Read the conflict notice and choose your draft or the server version deliberately. Refresh before retrying an uncertain write. Do not use **Paketi temizle** as a refresh action; it is destructive.

Saving edits does not automatically render or publish. If the render is stale, choose **Kaydedilmiş montajı render et** again after saving. If it remains queued, check worker status. If a media preview fails, use its reload/retry control before deciding that the source is lost.

## Instagram connection problems

Check the connection status on **Kontrol Paneli** and **Ayarlar**. Reconnect through the supported flow or provide a valid independently obtained token. Tokens need the correct account and permissions, not only a future expiry date. Do not paste tokens into bug reports or screenshots.

An operator may need to correct Meta application configuration, registered callback URLs, permissions, encryption settings, or public HTTPS access. Local HTTP startup does not meet Instagram’s public media-fetch requirements.

## Publication failures

![Publication review and decision controls](../../web/public/promotion/web/review.png)

| State | Safe next action |
| --- | --- |
| Preparing / render queued | Wait for the worker. Inspect worker health if it does not progress. |
| Stale render | Save intended edits and prepare a new render/review. Do not approve an old revision. |
| Review changed / already handled | Refresh. Another client may have acted; do not overwrite its decision. |
| Publishing / not yet confirmed | Watch the dashboard. Do not send another approval while confirmation is pending. |
| Failed | Read the error. Check the Instagram connection and public HTTPS media access before retrying an available action. |
| Uncertain | Check Instagram and current application state first. A lost response does not prove that publication failed. If the post already exists, follow the interface’s skip option rather than approving again. |

No failure state is presented as successful completion. Only Instagram-confirmed publication enters **Tamamlanmış paketler**.

## Connection or pairing lost

When live synchronization is unavailable, the app can preserve visible data and drafts while disabling unsafe edits. Wait for reconnection or use the retry action. Do not treat stale information as fresh confirmation.

If pairing is revoked, obtain a new one-time code from the intended installation and pair again. Do not recover browser authentication by copying credentials from another device.

## Inspect history and ask for help

Open **Etkinlik** for the recorded actions and **Tamamlanmış paketler** for read-only confirmed publications. Include the visible state, approximate time, and safe reproduction steps in a report. Exclude media without permission, tokens, pairing codes, private URLs, and environment files.

For a UI reminder, choose **Yardım → Tanıtımları yeniden başlat**. Tour progress stays in the browser; it does not change product state or grant consent.
