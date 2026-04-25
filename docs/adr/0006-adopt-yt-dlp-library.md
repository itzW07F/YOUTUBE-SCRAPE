# ADR 0006: Adopt yt-dlp as bundled library for video downloads

## Status

Accepted (supersedes ADR 0004)

## Context

ADR 0004 proposed an in-tree downloader that does not invoke `yt-dlp`. After extensive development effort, we identified fundamental limitations:

1. **Buffer Limitation**: YouTube's web player only maintains a ~22 second DASH buffer window. Capturing more would require playing the entire video.

2. **UMP Format Corruption**: YouTube wraps media data in UMP (Universal Media Protocol) protobuf messages inside mdat boxes. Unwrapping these correctly is complex and was corrupting AV1 bitstreams.

3. **403 Errors on Range Requests**: Direct HTTP range requests to googlevideo.com fail with 403 unless using proper browser impersonation (TLS fingerprinting, cookies, authentication tokens).

4. **Deciphering Complexity**: YouTube's signature and n-parameter transforms change weekly. Replicating yt-dlp's sophisticated JS challenge solving requires:
   - Multiple JS runtime integrations (Node.js, Deno, Bun, QuickJS)
   - Multi-client API strategy (android_vr, web_safari, tv_downgraded)
   - Browser impersonation via curl_cffi
   - Caching and bulk challenge solving
   - Estimated ~3-6 months of dedicated development

Meanwhile, `yt-dlp` already solves all these problems:
- Full video downloads via various extraction methods
- Robust deciphering with multiple fallback strategies
- Active maintenance by dedicated team (~weekly updates)
- Python API available as a library (`from yt_dlp import YoutubeDL`)

## Decision

- **Primary**: Use `yt-dlp` as a **bundled Python dependency** for all video/audio downloads.
  - Import and use `yt_dlp.YoutubeDL` API directly
  - Remove `--use-yt-dlp` flag (now default behavior)
  - yt-dlp is added to `pyproject.toml` dependencies

- **Fallback**: Keep experimental browser-based download **only** for audio/MP3 extraction when yt-dlp fails or is unavailable.
  - Use `--experimental-fallback` flag to enable
  - Mark as deprecated with warnings
  - Limitations (~22s clips, UMP issues) are acceptable for niche fallback use case

- **Scope Separation**:
  - **yt-dlp**: Video downloads (muxed A+V), reliable full files
  - **Camoufox**: Metadata scraping (comments, thumbnails, transcripts), audio/MP3 fallback

## Consequences

**Pros**:
- **Reliability**: Full video downloads work correctly without ~22s limitation
- **Maintainability**: External dependency maintained by dedicated team
- **Simplicity**: ~2000 lines of complex experimental download code moved to fallback path
- **Performance**: No browser overhead for video downloads (direct HTTP)
- **Future-proof**: yt-dlp's active development keeps pace with YouTube changes

**Cons**:
- **External Dependency**: Core functionality relies on external package (mitigated by bundling)
- **Heavier Install**: yt-dlp + curl_cffi increases package size (~3-5MB)
- **Version Drift**: Must periodically update yt-dlp dependency version
- **API Changes**: yt-dlp API changes could require code updates

## Migration

**For Users**:
- `youtube-scrape download URL -o out.mp4` - Works with full videos (no changes)
- Remove `--use-yt-dlp` flag (now default)
- Use `--experimental-fallback` if yt-dlp fails for audio extraction

**For Developers**:
- New code should use `DownloadService` facade
- `DownloadMediaService` becomes internal fallback only
- Experimental code marked deprecated, scheduled for future removal

## References

- yt-dlp Python API: https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp
- ADR 0004 (superseded): In-tree downloader strategy
- Related: `src/youtube_scrape/application/download_service.py`
- Related: `src/youtube_scrape/application/yt_dlp_service.py`