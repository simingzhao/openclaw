#!/bin/bash
# Map-Reduce summarization for long YouTube videos
# Usage: ./summarize_long.sh <video_url_or_id> [output_dir]
#
# This script handles videos with very long transcripts (1h+) by:
# 1. Fetching the full transcript
# 2. Splitting into ~20KB chunks
# 3. Extracting key points from each chunk (Map)
# 4. Merging all points into a comprehensive summary (Reduce)

set -e

VIDEO_ID="$1"
OUTPUT_DIR="${2:-/tmp}"
CHUNK_SIZE=20000  # bytes per chunk

if [ -z "$VIDEO_ID" ]; then
    echo "Usage: $0 <video_url_or_id> [output_dir]"
    exit 1
fi

# Extract video ID from URL if needed
if [[ "$VIDEO_ID" == *"youtube.com"* ]] || [[ "$VIDEO_ID" == *"youtu.be"* ]]; then
    VIDEO_ID=$(echo "$VIDEO_ID" | sed -E 's/.*[?&]v=([^&]+).*/\1/' | sed -E 's/.*youtu\.be\/([^?]+).*/\1/')
fi

echo "📺 Processing video: $VIDEO_ID"

# Step 1: Get video info
echo "📋 Fetching video info..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VIDEO_INFO=$(python3 "$SCRIPT_DIR/yt.py" info "$VIDEO_ID" 2>/dev/null || echo "{}")
VIDEO_TITLE=$(echo "$VIDEO_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title','Unknown'))" 2>/dev/null || echo "Unknown")
VIDEO_DURATION=$(echo "$VIDEO_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('duration','Unknown'))" 2>/dev/null || echo "Unknown")
CHANNEL_NAME=$(echo "$VIDEO_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('channelTitle','Unknown'))" 2>/dev/null || echo "Unknown")

echo "   Title: $VIDEO_TITLE"
echo "   Duration: $VIDEO_DURATION"
echo "   Channel: $CHANNEL_NAME"

# Step 2: Fetch transcript
echo "📝 Fetching transcript (this may take a while for long videos)..."
TRANSCRIPT_FILE="$OUTPUT_DIR/transcript_${VIDEO_ID}.txt"

# Try summarize CLI first (uses Apify for better reliability)
if command -v summarize &> /dev/null; then
    summarize "https://www.youtube.com/watch?v=$VIDEO_ID" --youtube auto --extract-only 2>&1 | grep -v "^Transcript:" > "$TRANSCRIPT_FILE" || true
fi

# Fallback to yt.py if summarize failed
if [ ! -s "$TRANSCRIPT_FILE" ]; then
    python3 "$SCRIPT_DIR/yt.py" transcript "$VIDEO_ID" --out "$TRANSCRIPT_FILE" 2>/dev/null || true
fi

if [ ! -s "$TRANSCRIPT_FILE" ]; then
    echo "❌ Failed to fetch transcript"
    exit 1
fi

TRANSCRIPT_SIZE=$(wc -c < "$TRANSCRIPT_FILE")
TRANSCRIPT_LINES=$(wc -l < "$TRANSCRIPT_FILE")
echo "   Transcript: ${TRANSCRIPT_SIZE} bytes, ${TRANSCRIPT_LINES} lines"

# Step 3: Split into chunks
echo "✂️  Splitting transcript into chunks..."
CHUNK_DIR="$OUTPUT_DIR/chunks_${VIDEO_ID}"
rm -rf "$CHUNK_DIR"
mkdir -p "$CHUNK_DIR"
split -b $CHUNK_SIZE "$TRANSCRIPT_FILE" "$CHUNK_DIR/chunk_"
CHUNK_COUNT=$(ls "$CHUNK_DIR" | wc -l | tr -d ' ')
echo "   Created $CHUNK_COUNT chunks"

# Step 4: Map - Extract points from each chunk
echo "🗺️  Extracting key points from each chunk (Map phase)..."
POINTS_DIR="$OUTPUT_DIR/points_${VIDEO_ID}"
rm -rf "$POINTS_DIR"
mkdir -p "$POINTS_DIR"

MAP_PROMPT="这是YouTube视频transcript的一部分。请提取8-10个核心要点/观点/金句，涵盖：观点、案例、数据、工具、方法论等。每个要点一行，用bullet point，保留具体细节（数字、名称等）。必须包含原文引用（用引号标注）。"

# Process chunks in parallel (max 3 concurrent to avoid rate limits)
chunk_num=0
for chunk in "$CHUNK_DIR"/chunk_*; do
    chunk_name=$(basename "$chunk")
    ((chunk_num++))
    echo "   Processing chunk $chunk_num/$CHUNK_COUNT..."
    cat "$chunk" | gemini "$MAP_PROMPT" > "$POINTS_DIR/$chunk_name.txt" 2>&1 &
    
    # Limit parallelism to avoid rate limits
    if (( chunk_num % 3 == 0 )); then
        wait
    fi
done
wait

echo "   Map phase complete"

# Step 5: Reduce - Merge all points into final summary
echo "📊 Generating comprehensive summary (Reduce phase)..."
ALL_POINTS_FILE="$OUTPUT_DIR/all_points_${VIDEO_ID}.txt"
cat "$POINTS_DIR"/*.txt | grep -v "^Loaded\|^Hook\|^Attempt\|^$" > "$ALL_POINTS_FILE"

REDUCE_PROMPT="以下是YouTube视频《${VIDEO_TITLE}》（频道: ${CHANNEL_NAME}，时长: ${VIDEO_DURATION}）的完整要点。请生成一份非常详尽的中文总结报告，要求：

1. **视频概述**（4-5句话）
2. **核心理念**（6-8条，每条3-4句详细展开，必须包含原文引用）
3. **具体配置与工具**（详细列出所有提到的硬件、软件、数据等，用表格）
4. **方法论与技巧**（6-8条具体可操作的方法，附带案例）
5. **金句与原文摘录**（8-10句经典原话，中英对照）
6. **案例故事**（视频中提到的经历、案例等）
7. **行动建议**（针对不同情况的详细建议）

要求：大量引用原文，用引号标注。内容详尽，不要压缩。输出至少2000字。"

SUMMARY_FILE="$OUTPUT_DIR/summary_${VIDEO_ID}.md"
cat "$ALL_POINTS_FILE" | gemini "$REDUCE_PROMPT" > "$SUMMARY_FILE" 2>&1

# Step 6: Generate final markdown with metadata
echo "📄 Generating final markdown..."
FINAL_FILE="$OUTPUT_DIR/${VIDEO_ID}_full.md"
cat > "$FINAL_FILE" << HEADER
# ${VIDEO_TITLE}
- 频道: ${CHANNEL_NAME}
- 链接: https://www.youtube.com/watch?v=${VIDEO_ID}
- 时长: ${VIDEO_DURATION}
- 生成时间: $(date +%Y-%m-%d)

---

HEADER

cat "$SUMMARY_FILE" >> "$FINAL_FILE"

cat >> "$FINAL_FILE" << FOOTER

---

*由小龙虾 🦞 通过 Map-Reduce 方法自动总结*
FOOTER

echo ""
echo "✅ Done! Output files:"
echo "   Summary: $FINAL_FILE"
echo "   Transcript: $TRANSCRIPT_FILE"
echo "   All points: $ALL_POINTS_FILE"

# Cleanup temp files
rm -rf "$CHUNK_DIR" "$POINTS_DIR"
