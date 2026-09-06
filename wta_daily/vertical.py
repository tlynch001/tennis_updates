from __future__ import annotations
import argparse
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw
from wta_daily.config import GraphicsConfig, load_config
from wta_daily.countries import get_country_info
from wta_daily.graphics.flags import render_flag
from wta_daily.graphics.fonts import load_font
from wta_daily.graphics.utils import fit_text, hex_to_rgb, movement_color, movement_headline_text
from wta_daily.models import DailyReport, FeaturedPlayerReport, PlayerReport
from wta_daily.persistence.report_store import DailyOutputStore
from wta_daily.tour import profile_for
from wta_daily.voice.narration_timing import NarrationSegment, read_timing_file
logger = logging.getLogger(__name__)
PORTRAIT_WIDTH = 1080
PORTRAIT_HEIGHT = 1920
_MIN_SLIDE_SECONDS = 0.1

def _portrait_config(source: GraphicsConfig) -> GraphicsConfig:
    return replace(source, width=PORTRAIT_WIDTH, height=PORTRAIT_HEIGHT)

def _font_that_fits(draw, text: str, *, font_path: str | None, start_size: int, min_size: int, max_width: int, bold: bool=False):
    for size in range(start_size, min_size - 1, -1):
        font = load_font(font_path, size=size, bold=bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return load_font(font_path, size=min_size, bold=bold)

def _draw_header(draw: ImageDraw.ImageDraw, *, width: int, height: int, panel: tuple[int, int, int], accent: tuple[int, int, int], text_color: tuple[int, int, int], subtext_color: tuple[int, int, int], theme, title: str, subtitle: str, right_text: str | None=None) -> int:
    header_h = int(height * 0.115)
    draw.rectangle([0, 0, width, header_h], fill=panel)
    stripe_h = max(6, int(height * 0.004))
    draw.rectangle([0, header_h - stripe_h, width, header_h], fill=accent)
    title_font = load_font(theme.font_bold, size=int(header_h * 0.3), bold=True)
    subtitle_font = load_font(theme.font_regular, size=int(header_h * 0.16))
    x = int(width * 0.055)
    draw.text((x, int(header_h * 0.2)), title, font=title_font, fill=text_color, anchor='la')
    draw.text((x, int(header_h * 0.66)), subtitle, font=subtitle_font, fill=subtext_color, anchor='la')
    if right_text:
        right_font = load_font(theme.font_bold, size=int(header_h * 0.13), bold=True)
        draw.text((int(width * 0.945), int(header_h * 0.72)), right_text, font=right_font, fill=accent, anchor='ra')
    return header_h

def render_vertical_leaderboard(report: DailyReport, output_path: Path, graphics: GraphicsConfig) -> Path:
    theme = graphics.theme
    width, height = (graphics.width, graphics.height)
    bg = hex_to_rgb(theme.background_color)
    panel = hex_to_rgb(theme.panel_color)
    accent = hex_to_rgb(theme.accent_color)
    text_color = hex_to_rgb(theme.text_color)
    subtext_color = hex_to_rgb(theme.subtext_color)
    img = Image.new('RGB', (width, height), bg)
    draw = ImageDraw.Draw(img)
    profile = profile_for(report.tour)
    header_h = _draw_header(draw, width=width, height=height, panel=panel, accent=accent, text_color=text_color, subtext_color=subtext_color, theme=theme, title=f'{profile.display_name} TOP {len(report.players)}', subtitle='OFFICIAL RANKINGS', right_text=report.report_date.strftime('%b %d').upper())
    footer_h = int(height * 0.045)
    top = header_h + int(height * 0.022)
    bottom = height - footer_h - int(height * 0.02)
    available = bottom - top
    count = max(1, len(report.players))
    gap = int(height * 0.007)
    row_h = int((available - gap * (count - 1)) / count)
    margin = int(width * 0.055)
    row_x2 = width - margin
    rank_font = load_font(theme.font_bold, size=int(row_h * 0.42), bold=True)
    name_font = load_font(theme.font_bold, size=int(row_h * 0.27), bold=True)
    country_font = load_font(theme.font_regular, size=int(row_h * 0.14))
    points_font = load_font(theme.font_bold, size=int(row_h * 0.25), bold=True)
    points_label_font = load_font(theme.font_regular, size=int(row_h * 0.105))
    move_font = load_font(theme.font_bold, size=int(row_h * 0.14), bold=True)
    alt_panel = tuple((int(panel[i] * 0.65 + bg[i] * 0.35) for i in range(3)))
    for index, player in enumerate(report.players):
        y1 = top + index * (row_h + gap)
        y2 = y1 + row_h
        row_fill = panel if index % 2 == 0 else alt_panel
        draw.rounded_rectangle([margin, y1, row_x2, y2], radius=max(8, int(row_h * 0.17)), fill=row_fill)
        rank_x = margin + int(width * 0.035)
        draw.text((rank_x, (y1 + y2) / 2), str(player.rank), font=rank_font, fill=accent, anchor='lm')
        flag_h = max(18, int(row_h * 0.23))
        flag_img = render_flag(player.country_code, flag_h)
        flag_x = margin + int(width * 0.115)
        flag_y = int(y1 + row_h * 0.2)
        img.paste(flag_img, (flag_x, flag_y), flag_img)
        name_x = flag_x + flag_img.width + int(width * 0.025)
        points_right = row_x2 - int(width * 0.035)
        reserved_right = int(width * 0.32)
        max_name_width = max(120, points_right - reserved_right - name_x)
        fitted = fit_text(draw, player.name, name_font, max_name_width)
        draw.text((name_x, y1 + row_h * 0.24), fitted, font=name_font, fill=text_color, anchor='la')
        country = get_country_info(player.country_code).display_name
        draw.text((name_x, y1 + row_h * 0.62), country, font=country_font, fill=subtext_color, anchor='la')
        draw.text((points_right, y1 + row_h * 0.25), f'{player.points:,}', font=points_font, fill=text_color, anchor='ra')
        draw.text((points_right, y1 + row_h * 0.62), 'POINTS', font=points_label_font, fill=subtext_color, anchor='ra')
        move = movement_headline_text(player.movement, rank=player.rank, top_n=len(report.players), previous_rank=player.previous_rank)
        draw.text((points_right, y1 + row_h * 0.8), move, font=move_font, fill=movement_color(player.movement, theme), anchor='ra')
    footer_font = load_font(theme.font_regular, size=int(footer_h * 0.3))
    draw.text((width / 2, height - footer_h / 2), profile.attribution, font=footer_font, fill=subtext_color, anchor='mm')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, 'PNG')
    return output_path

def _render_person_card(*, name: str, country_code: str, rank: int | None, points: int | None, movement, previous_rank: int | None, match, match_error: str | None, output_path: Path, graphics: GraphicsConfig, top_n: int, supports_daily_matches: bool, featured_label: str | None=None) -> Path:
    theme = graphics.theme
    width, height = (graphics.width, graphics.height)
    bg = hex_to_rgb(theme.background_color)
    panel = hex_to_rgb(theme.panel_color)
    accent = hex_to_rgb(theme.accent_color)
    text_color = hex_to_rgb(theme.text_color)
    subtext_color = hex_to_rgb(theme.subtext_color)
    img = Image.new('RGB', (width, height), bg)
    draw = ImageDraw.Draw(img)
    stripe_w = max(10, int(width * 0.018))
    draw.rectangle([0, 0, stripe_w, height], fill=accent)
    margin = int(width * 0.075)
    kicker_font = load_font(theme.font_bold, size=int(height * 0.026), bold=True)
    rank_font = load_font(theme.font_bold, size=int(height * 0.105), bold=True)
    country_font = load_font(theme.font_regular, size=int(height * 0.021))
    points_font = load_font(theme.font_bold, size=int(height * 0.068), bold=True)
    points_label_font = load_font(theme.font_regular, size=int(height * 0.019))
    badge_font = load_font(theme.font_bold, size=int(height * 0.022), bold=True)
    section_font = load_font(theme.font_bold, size=int(height * 0.021), bold=True)
    result_font = load_font(theme.font_bold, size=int(height * 0.035), bold=True)
    detail_font = load_font(theme.font_regular, size=int(height * 0.026))
    y = int(height * 0.06)
    if featured_label:
        label_w = draw.textlength(featured_label, font=kicker_font) + width * 0.08
        label_h = int(height * 0.045)
        draw.rounded_rectangle([margin, y, margin + label_w, y + label_h], radius=int(label_h * 0.45), fill=accent)
        draw.text((margin + label_w / 2, y + label_h / 2), featured_label, font=kicker_font, fill=bg, anchor='mm')
        y += label_h + int(height * 0.035)
    rank_text = f'#{rank}' if rank is not None else 'UNRANKED'
    draw.text((margin, y), rank_text, font=rank_font, fill=accent, anchor='la')
    rank_bbox = draw.textbbox((margin, y), rank_text, font=rank_font, anchor='la')
    y = rank_bbox[3] + int(height * 0.025)
    flag_h = int(height * 0.043)
    flag_img = render_flag(country_code, flag_h)
    img.paste(flag_img, (margin, y), flag_img)
    name_x = margin + flag_img.width + int(width * 0.025)
    max_name_w = width - name_x - margin
    name_font = _font_that_fits(draw, name, font_path=theme.font_bold, start_size=int(height * 0.044), min_size=int(height * 0.028), max_width=max_name_w, bold=True)
    draw.text((name_x, y), name, font=name_font, fill=text_color, anchor='la')
    name_bbox = draw.textbbox((name_x, y), name, font=name_font, anchor='la')
    country = get_country_info(country_code).display_name
    draw.text((name_x, name_bbox[3] + height * 0.008), country, font=country_font, fill=subtext_color, anchor='la')
    metrics_top = int(height * 0.34)
    draw.rounded_rectangle([margin, metrics_top, width - margin, int(height * 0.51)], radius=int(height * 0.018), fill=panel)
    points_value = f'{points:,}' if points is not None else '—'
    draw.text((margin * 1.45, metrics_top + height * 0.045), points_value, font=points_font, fill=text_color, anchor='la')
    draw.text((margin * 1.45, metrics_top + height * 0.12), 'RANKING POINTS', font=points_label_font, fill=subtext_color, anchor='la')
    if movement is not None and rank is not None:
        movement_text = movement_headline_text(movement, rank=rank, top_n=top_n, previous_rank=previous_rank)
        badge_color = movement_color(movement, theme)
        badge_w = min(width * 0.45, draw.textlength(movement_text, font=badge_font) + width * 0.08)
        badge_h = int(height * 0.055)
        badge_x2 = width - margin * 1.45
        badge_x1 = badge_x2 - badge_w
        badge_y1 = metrics_top + int(height * 0.065)
        draw.rounded_rectangle([badge_x1, badge_y1, badge_x2, badge_y1 + badge_h], radius=int(badge_h * 0.35), outline=badge_color, width=3)
        draw.text(((badge_x1 + badge_x2) / 2, badge_y1 + badge_h / 2), movement_text, font=badge_font, fill=badge_color, anchor='mm')
    match_top = int(height * 0.53)
    match_bottom = int(height * 0.84)
    draw.rounded_rectangle([margin, match_top, width - margin, match_bottom], radius=int(height * 0.02), fill=panel)
    section_label = "YESTERDAY'S MATCH" if supports_daily_matches else 'RANKING UPDATE'
    draw.text((margin * 1.45, match_top + height * 0.045), section_label, font=section_font, fill=subtext_color, anchor='la')
    if match is not None:
        outcome = 'WON' if match.won else 'LOST'
        outcome_color = hex_to_rgb(theme.up_color) if match.won else hex_to_rgb(theme.down_color)
        opponent_line = f'{outcome} vs {match.opponent}'
        opponent_font = _font_that_fits(draw, opponent_line, font_path=theme.font_bold, start_size=int(height * 0.035), min_size=int(height * 0.024), max_width=int(width - margin * 3), bold=True)
        draw.text((margin * 1.45, match_top + height * 0.105), opponent_line, font=opponent_font, fill=outcome_color, anchor='la')
        score_line = match.score or 'Score unavailable'
        draw.text((margin * 1.45, match_top + height * 0.18), score_line, font=result_font, fill=text_color, anchor='la')
        tournament_line = match.tournament
        if match.round:
            tournament_line += f' — {match.round}'
        tournament_line = fit_text(draw, tournament_line, detail_font, int(width - margin * 3))
        draw.text((margin * 1.45, match_top + height * 0.245), tournament_line, font=detail_font, fill=text_color, anchor='la')
        date_label = f'{match.match_date:%B} {match.match_date.day}, {match.match_date.year}' if match.match_date else 'Date unconfirmed'
        draw.text((margin * 1.45, match_top + height * 0.295), date_label, font=detail_font, fill=subtext_color, anchor='la')
    else:
        if not supports_daily_matches:
            message = f'{points:,} ranking points' if points is not None else 'Ranking points unavailable'
        elif match_error:
            message = 'Match data unavailable today.'
        else:
            message = 'Did not play yesterday.'
        message_font = _font_that_fits(draw, message, font_path=theme.font_bold, start_size=int(height * 0.035), min_size=int(height * 0.024), max_width=int(width - margin * 3), bold=True)
        draw.text((margin * 1.45, match_top + height * 0.12), message, font=message_font, fill=subtext_color, anchor='la')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, 'PNG')
    return output_path

def render_vertical_player_card(player: PlayerReport, output_path: Path, graphics: GraphicsConfig, *, top_n: int, supports_daily_matches: bool) -> Path:
    return _render_person_card(name=player.name, country_code=player.country_code, rank=player.rank, points=player.points, movement=player.movement, previous_rank=player.previous_rank, match=player.match, match_error=player.match_error, output_path=output_path, graphics=graphics, top_n=top_n, supports_daily_matches=supports_daily_matches)

def render_vertical_featured_card(featured: FeaturedPlayerReport, output_path: Path, graphics: GraphicsConfig, *, top_n: int, supports_daily_matches: bool) -> Path:
    return _render_person_card(name=featured.name, country_code=featured.country_code, rank=featured.rank, points=featured.points, movement=featured.movement, previous_rank=featured.previous_rank, match=featured.match, match_error=featured.match_error, output_path=output_path, graphics=graphics, top_n=top_n, supports_daily_matches=supports_daily_matches, featured_label='FEATURED PLAYER')

def _image_for_segment(segment: NarrationSegment, vertical_root: Path) -> Path:
    leaderboard = vertical_root / 'leaderboard.png'
    if segment.kind in ('intro', 'closer'):
        return leaderboard
    if segment.kind == 'player' and segment.rank is not None:
        card = vertical_root / 'player_cards' / f'{segment.rank:02d}.png'
        return card if card.exists() else leaderboard
    if segment.kind == 'featured':
        featured = vertical_root / 'featured_player.png'
        return featured if featured.exists() else leaderboard
    return leaderboard

def _merge_consecutive_identical_images(slides: list[tuple[Path, float]]) -> list[tuple[Path, float]]:
    if not slides:
        return slides
    merged = [slides[0]]
    for image_path, duration in slides[1:]:
        last_image, last_duration = merged[-1]
        if image_path == last_image:
            merged[-1] = (last_image, last_duration + duration)
        else:
            merged.append((image_path, duration))
    return merged

def assemble_vertical_video(*, source_store: DailyOutputStore, vertical_root: Path, fps: int) -> Path:
    if shutil.which('ffmpeg') is None:
        raise RuntimeError('ffmpeg was not found on PATH; cannot assemble vertical video.')
    if not source_store.narration_path.exists():
        raise RuntimeError(f'Missing narration audio: {source_store.narration_path}')
    segments = read_timing_file(source_store.timing_path)
    if not segments:
        raise RuntimeError(f"Missing or unusable narration timing: {source_store.timing_path}. Vertical rerender intentionally requires the completed run's timing file.")
    slides = _merge_consecutive_identical_images([(_image_for_segment(segment, vertical_root), max(segment.duration_seconds, _MIN_SLIDE_SECONDS)) for segment in segments])
    for image_path, _duration in slides:
        if not image_path.exists():
            raise RuntimeError(f'Missing vertical slide: {image_path}')
    concat_path = vertical_root / 'concat_list.txt'
    with concat_path.open('w', encoding='utf-8') as fh:
        for image_path, duration in slides:
            fh.write(f"file '{image_path.resolve()}'\n")
            fh.write(f'duration {duration}\n')
        fh.write(f"file '{slides[-1][0].resolve()}'\n")
    silent_path = vertical_root / '.silent_vertical.mp4'
    output_path = vertical_root / 'video.mp4'
    build = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_path), '-vf', f'scale={PORTRAIT_WIDTH}:{PORTRAIT_HEIGHT},fps={fps}', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', str(silent_path)]
    mux = ['ffmpeg', '-y', '-i', str(silent_path), '-i', str(source_store.narration_path), '-c:v', 'copy', '-c:a', 'aac', '-shortest', str(output_path)]
    for command in (build, mux):
        logger.debug('Running: %s', ' '.join(command))
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f'ffmpeg failed: {result.stderr[-2000:]}')
    silent_path.unlink(missing_ok=True)
    concat_path.unlink(missing_ok=True)
    return output_path

def rerender_vertical(config_path: str | Path, report_date: date) -> Path:
    config = load_config(config_path)
    source_store = DailyOutputStore(config.output_dir, report_date)
    if not source_store.report_path.exists():
        raise FileNotFoundError(f'No completed report found at {source_store.report_path}; run the normal pipeline first.')
    with source_store.report_path.open('r', encoding='utf-8') as fh:
        report = DailyReport.from_dict(json.load(fh))
    graphics = _portrait_config(config.graphics)
    vertical_root = source_store.root / 'vertical'
    cards_dir = vertical_root / 'player_cards'
    cards_dir.mkdir(parents=True, exist_ok=True)
    profile = profile_for(report.tour)
    render_vertical_leaderboard(report, vertical_root / 'leaderboard.png', graphics)
    for player in report.players:
        render_vertical_player_card(player, cards_dir / f'{player.rank:02d}.png', graphics, top_n=config.top_n, supports_daily_matches=profile.supports_daily_matches)
    if report.featured_player is not None:
        render_vertical_featured_card(report.featured_player, vertical_root / 'featured_player.png', graphics, top_n=config.top_n, supports_daily_matches=profile.supports_daily_matches)
    output_path = assemble_vertical_video(source_store=source_store, vertical_root=vertical_root, fps=config.video.fps)
    logger.info('Vertical video created: %s', output_path)
    return output_path

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='wta-daily-vertical', description='Rerender an existing completed WTA/ATP run as a 1080x1920 vertical video.')
    parser.add_argument('--config', default='config/config.yaml', help='Path to the existing YAML configuration file.')
    parser.add_argument('--date', required=True, help='Completed report date to rerender (YYYY-MM-DD).')
    parser.add_argument('--verbose', action='store_true', help='Enable debug logging.')
    return parser

def main(argv: list[str] | None=None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    try:
        report_date = date.fromisoformat(args.date)
        output_path = rerender_vertical(args.config, report_date)
    except Exception as exc:
        logger.exception('Vertical rerender failed: %s', exc)
        return 1
    print(output_path)
    return 0
if __name__ == '__main__':
    sys.exit(main())
