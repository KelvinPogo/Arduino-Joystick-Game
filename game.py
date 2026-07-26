"""Superhero vs. Enemies - a simple 2D shooter controlled by an Arduino joystick.

Controls:
  Joystick               - move the hero around the arena
  External shoot button  - shoot in the direction you're facing
  External shield button - activate shield (when the shield icon is showing)
  Joystick button        - restart after game over
  E                      - activate shield (when the shield icon is showing)
  (Fallback) WASD/Arrows to move, Space to shoot, R to restart, Esc to quit.

Every 20 seconds a shield icon appears at the top of the screen; press E while
it's showing to become invulnerable for 6 seconds.
"""

import math
import random
import sys

import numpy as np
import pygame

import sounds
from joystick_input import JoystickReader

WIDTH, HEIGHT = 800, 800
ARENA_MARGIN = 40
ARENA = pygame.Rect(
    ARENA_MARGIN, ARENA_MARGIN,
    WIDTH - 2 * ARENA_MARGIN, HEIGHT - 2 * ARENA_MARGIN,
)

PLAYER_RADIUS = 20
PLAYER_SPEED = 320.0  # pixels/sec at full joystick deflection
PLAYER_MAX_LIVES = 3
INVULNERABLE_TIME = 1.2
RUN_ANIM_SPEED = 11.0  # radians/sec of the boot-bounce phase while moving

BULLET_RADIUS = 5
BULLET_SPEED = 520.0
SHOOT_COOLDOWN = 0.25

ENEMY_RADIUS = 16
ENEMY_SPEED = 90.0
SPAWN_INTERVAL_START = 1.3
SPAWN_INTERVAL_MIN = 0.45

POWERUP_RADIUS = 24
POWERUP_SPAWN_INTERVAL = 15.0
POWERUP_HEAL_AMOUNT = 1

SHIELD_COOLDOWN = 20.0
SHIELD_DURATION = 6.0

BOSS_TRIGGER_TIME = 60.0  # seconds of gameplay before the boss shows up
BOSS_RADIUS = 55
BOSS_SPEED = 110.0  # faster than a regular enemy
BOSS_DESCEND_SPEED = 100.0
BOSS_DESCEND_TARGET_Y_OFFSET = 140
BOSS_HP = 45
BOSS_RING_INTERVAL_MIN = 2.5
BOSS_RING_INTERVAL_MAX = 4.0
BOSS_RING_PROJECTILE_COUNT = 10
BOSS_PROJECTILE_SPEED = 220.0
BOSS_SHIELD_ROLL_INTERVAL = 3.0
BOSS_SHIELD_CHANCE = 0.7
BOSS_SHIELD_DURATION = 3.5
BOSS_TELEPORT_INTERVAL_MIN = 4.0
BOSS_TELEPORT_INTERVAL_MAX = 7.0

WIN_LINGER_TIME = 5.0  # seconds the "You Win" screen ignores restart input

PIXEL_SCALE = 2  # world is rendered at 1/PIXEL_SCALE resolution, then scaled back up (chunky pixel-art look)

# Gungeon-ish dungeon palette: warm torch light against cold brick shadow.
BG_COLOR = (10, 8, 10)
ARENA_COLOR = (46, 38, 34)
ARENA_COLOR_ALT = (40, 33, 30)
ARENA_GRID_COLOR = (26, 20, 18)
ARENA_BORDER = (94, 46, 34)
# Futuristic-soldier palette: dark tactical armor with a glowing visor/chest accent.
ARMOR_BODY = (56, 66, 78)
ARMOR_SHOULDER = (44, 52, 62)
ARMOR_ACCENT = (90, 210, 220)
HELMET_COLOR = (38, 44, 52)
VISOR_COLOR = (110, 235, 245)
BOOT_COLOR = (30, 30, 34)
GUN_COLOR = (32, 32, 36)
GUN_GRIP_COLOR = (58, 58, 64)
BULLET_COLOR = (255, 224, 120)
ENEMY_COLOR = (206, 160, 64)
POWERUP_COLOR = (96, 196, 96)
SHIELD_COLOR = (110, 200, 235)
TEXT_COLOR = (232, 214, 180)
BOSS_COLOR = (150, 58, 46)
BOSS_ARM_COLOR = (112, 44, 34)
BOSS_EYE_COLOR = (255, 221, 64)
BOSS_PUPIL_COLOR = (24, 16, 10)
BOSS_MOUTH_COLOR = (18, 10, 8)
BOSS_TEETH_COLOR = (238, 228, 208)
WIN_COLOR = (140, 220, 120)
OUTLINE_COLOR = (26, 18, 14)
SHADOW_COLOR = (4, 3, 2, 120)
TORCH_COLOR = (255, 150, 60)
TORCH_RADIUS = 40  # small, subtle halo right at the flame - not a room-filling glow
TORCH_BRACKET_LENGTH = 22
TORCH_FLAME_OFFSET = 28


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _draw_shadow(surface, pos, rx, ry):
    """A soft dark ellipse under a sprite's feet, to sit it into the floor."""
    w, h = int(rx * 2), int(ry * 2)
    if w <= 0 or h <= 0:
        return
    shadow = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow, SHADOW_COLOR, shadow.get_rect())
    surface.blit(shadow, (pos.x - rx, pos.y + ry * 0.35))


def _build_vignette_surface(width, height):
    """Darkens the screen edges so the arena reads as lit from the middle out."""
    ys, xs = np.indices((height, width))
    cx, cy = width / 2, height / 2
    max_dist = math.hypot(cx, cy)
    dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / max_dist
    t = np.clip((dist - 0.35) / 0.65, 0, 1)
    alpha = (t ** 1.8 * 200).astype(np.uint8)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = 6
    rgba[..., 1] = 4
    rgba[..., 2] = 3
    rgba[..., 3] = alpha
    return pygame.image.frombuffer(rgba.tobytes(), (width, height), "RGBA").convert_alpha()


def _build_torch_glow(radius, color):
    """An additive warm bloom; color is premultiplied by falloff since BLEND_ADD ignores alpha."""
    size = radius * 2
    ys, xs = np.indices((size, size))
    cx = cy = radius
    dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) / radius
    intensity = np.clip(1 - dist, 0, 1) ** 2
    rgb = np.zeros((size, size, 3), dtype=np.uint8)
    for i in range(3):
        rgb[..., i] = (color[i] * intensity).astype(np.uint8)
    return pygame.image.frombuffer(rgb.tobytes(), (size, size), "RGB").convert()


def _build_arena_floor():
    """A tiled stone floor with mortar lines and scattered moss/bone/crack detail."""
    w, h = ARENA.width, ARENA.height
    surf = pygame.Surface((w, h))
    tile = 40
    for ty in range(0, h, tile):
        for tx in range(0, w, tile):
            shade = ARENA_COLOR if ((tx // tile) + (ty // tile)) % 2 == 0 else ARENA_COLOR_ALT
            pygame.draw.rect(surf, shade, (tx, ty, tile, tile))
    for tx in range(0, w + 1, tile):
        pygame.draw.line(surf, ARENA_GRID_COLOR, (tx, 0), (tx, h))
    for ty in range(0, h + 1, tile):
        pygame.draw.line(surf, ARENA_GRID_COLOR, (0, ty), (w, ty))

    rng = random.Random(7)  # fixed seed: floor detail is decorative, not gameplay-random
    for _ in range(90):
        x = rng.uniform(0, w)
        y = rng.uniform(0, h)
        roll = rng.random()
        if roll < 0.4:
            pygame.draw.circle(surf, (58, 84, 46), (x, y), rng.uniform(2, 5))
        elif roll < 0.7:
            pygame.draw.circle(surf, (16, 11, 9), (x, y), rng.uniform(1, 3))
        else:
            end = (x + rng.uniform(-12, 12), y + rng.uniform(-12, 12))
            pygame.draw.line(surf, (64, 48, 34), (x, y), end, 1)
    return surf.convert()


def _build_shield_surf(size, radius, color):
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    center = (size // 2, size // 2)
    pygame.draw.circle(surf, (*color, 90), center, radius)
    pygame.draw.circle(surf, (*color, 200), center, radius, 3)
    return surf




class Player:
    def __init__(self):
        self.pos = pygame.Vector2(ARENA.centerx, ARENA.centery)
        self.facing = pygame.Vector2(0, -1)
        self.lives = PLAYER_MAX_LIVES
        self.invulnerable = 0.0
        self.shield_timer = 0.0
        self.run_phase = 0.0
        self.moving = False

    @property
    def shielded(self):
        return self.shield_timer > 0

    def update(self, dt, move_x, move_y):
        move = pygame.Vector2(move_x, move_y)
        self.moving = move.length_squared() > 0
        if self.moving:
            if move.length() > 1:
                move.scale_to_length(1)
            self.facing = move.normalize()
            self.pos += move * PLAYER_SPEED * dt
            self.run_phase += dt * RUN_ANIM_SPEED
        else:
            self.run_phase = 0.0

        self.pos.x = clamp(self.pos.x, ARENA.left + PLAYER_RADIUS, ARENA.right - PLAYER_RADIUS)
        self.pos.y = clamp(self.pos.y, ARENA.top + PLAYER_RADIUS, ARENA.bottom - PLAYER_RADIUS)

        if self.invulnerable > 0:
            self.invulnerable = max(0.0, self.invulnerable - dt)
        if self.shield_timer > 0:
            self.shield_timer = max(0.0, self.shield_timer - dt)

    def hit(self):
        if self.shielded:
            return False
        if self.invulnerable <= 0:
            self.lives -= 1
            self.invulnerable = INVULNERABLE_TIME
            return True
        return False

    def draw(self, surface):
        flashing = self.invulnerable > 0 and int(self.invulnerable * 10) % 2 == 0
        if flashing:
            return
        _draw_shadow(surface, self.pos, PLAYER_RADIUS * 1.1, PLAYER_RADIUS * 0.5)
        if self.shielded:
            radius = PLAYER_RADIUS + 12
            shield_surf = _build_shield_surf(radius * 2 + 8, radius, SHIELD_COLOR)
            surface.blit(shield_surf, shield_surf.get_rect(center=self.pos))

        # Body stays in a fixed top-down orientation (as in most twin-stick shooters);
        # only the gun and visor swing toward self.facing, via plain vector offsets,
        # so there's no whole-body rotation to distort the silhouette.
        r = PLAYER_RADIUS

        for side_sign, phase_offset in ((-1, 0.0), (1, math.pi)):
            bob = abs(math.sin(self.run_phase + phase_offset)) * (r * 0.2) if self.moving else 0.0
            boot_rect = pygame.Rect(0, 0, r * 0.42, r * 0.55)
            boot_rect.center = (self.pos.x + side_sign * r * 0.38, self.pos.y + r * 0.95 - bob)
            pygame.draw.rect(surface, BOOT_COLOR, boot_rect, border_radius=3)

        torso_rect = pygame.Rect(0, 0, r * 1.05, r * 1.3)
        torso_rect.center = (self.pos.x, self.pos.y + r * 0.05)
        pygame.draw.rect(surface, ARMOR_BODY, torso_rect, border_radius=8)
        pygame.draw.rect(surface, OUTLINE_COLOR, torso_rect, 2, border_radius=8)

        for side_sign in (-1, 1):
            pad_rect = pygame.Rect(0, 0, r * 0.5, r * 0.5)
            pad_rect.center = (self.pos.x + side_sign * r * 0.72, self.pos.y - r * 0.2)
            pygame.draw.rect(surface, ARMOR_SHOULDER, pad_rect, border_radius=5)
            pygame.draw.rect(surface, OUTLINE_COLOR, pad_rect, 2, border_radius=5)

        chest_rect = pygame.Rect(0, 0, r * 0.32, r * 0.12)
        chest_rect.center = (self.pos.x, self.pos.y + r * 0.2)
        pygame.draw.rect(surface, ARMOR_ACCENT, chest_rect, border_radius=2)

        # Gun: a simple line/circle pivoting on self.pos, so it always points cleanly
        # toward self.facing with no shape-distortion risk.
        gun_base = self.pos + self.facing * (r * 0.3)
        gun_tip = self.pos + self.facing * (r * 1.9)
        pygame.draw.line(surface, GUN_COLOR, gun_base, gun_tip, 6)
        pygame.draw.circle(surface, GUN_GRIP_COLOR, gun_base, 5)

        # Helmet, fixed above the torso; the visor slides toward self.facing so it
        # still reads as "looking" the way the player is moving/aiming.
        helmet_center = pygame.Vector2(self.pos.x, self.pos.y - r * 0.62)
        pygame.draw.circle(surface, HELMET_COLOR, helmet_center, r * 0.62)
        pygame.draw.circle(surface, OUTLINE_COLOR, helmet_center, r * 0.62, 2)
        visor_center = helmet_center + self.facing * (r * 0.3)
        visor_rect = pygame.Rect(0, 0, r * 0.5, r * 0.22)
        visor_rect.center = visor_center
        pygame.draw.rect(surface, VISOR_COLOR, visor_rect, border_radius=3)


class Bullet:
    def __init__(self, pos, direction):
        self.pos = pygame.Vector2(pos)
        self.vel = direction * BULLET_SPEED

    def update(self, dt):
        self.pos += self.vel * dt

    def offscreen(self):
        return not ARENA.inflate(40, 40).collidepoint(self.pos)

    def draw(self, surface):
        pygame.draw.circle(surface, BULLET_COLOR, self.pos, BULLET_RADIUS + 2)
        pygame.draw.circle(surface, OUTLINE_COLOR, self.pos, BULLET_RADIUS + 2, 1)


class Enemy:
    def __init__(self):
        self.pos = self._spawn_point()

    def _spawn_point(self):
        side = random.choice(["top", "bottom", "left", "right"])
        if side == "top":
            return pygame.Vector2(random.uniform(ARENA.left, ARENA.right), ARENA.top)
        if side == "bottom":
            return pygame.Vector2(random.uniform(ARENA.left, ARENA.right), ARENA.bottom)
        if side == "left":
            return pygame.Vector2(ARENA.left, random.uniform(ARENA.top, ARENA.bottom))
        return pygame.Vector2(ARENA.right, random.uniform(ARENA.top, ARENA.bottom))

    def update(self, dt, target_pos):
        direction = target_pos - self.pos
        if direction.length_squared() > 0:
            direction.normalize_ip()
            self.pos += direction * ENEMY_SPEED * dt

    def draw(self, surface):
        _draw_shadow(surface, self.pos, ENEMY_RADIUS * 1.1, ENEMY_RADIUS * 0.5)
        pygame.draw.circle(surface, ENEMY_COLOR, self.pos, ENEMY_RADIUS)
        pygame.draw.circle(surface, OUTLINE_COLOR, self.pos, ENEMY_RADIUS, 2)


class BossProjectile:
    """Same shape/color as a regular enemy, but flies in a straight line."""

    def __init__(self, pos, direction):
        self.pos = pygame.Vector2(pos)
        self.vel = direction * BOSS_PROJECTILE_SPEED

    def update(self, dt):
        self.pos += self.vel * dt

    def offscreen(self):
        return not ARENA.inflate(40, 40).collidepoint(self.pos)

    def draw(self, surface):
        pygame.draw.circle(surface, ENEMY_COLOR, self.pos, ENEMY_RADIUS)
        pygame.draw.circle(surface, OUTLINE_COLOR, self.pos, ENEMY_RADIUS, 2)


class Boss:
    def __init__(self):
        self.pos = pygame.Vector2(ARENA.centerx, ARENA.top - BOSS_RADIUS)
        self.facing = pygame.Vector2(0, 1)
        self.hp = BOSS_HP
        self.descending = True
        self.target_y = ARENA.top + BOSS_DESCEND_TARGET_Y_OFFSET
        self.shield_timer = 0.0
        self.shield_roll_timer = BOSS_SHIELD_ROLL_INTERVAL
        self.ring_timer = random.uniform(BOSS_RING_INTERVAL_MIN, BOSS_RING_INTERVAL_MAX)
        self.teleport_timer = random.uniform(BOSS_TELEPORT_INTERVAL_MIN, BOSS_TELEPORT_INTERVAL_MAX)
        self.teleport_flash = 0.0

    @property
    def shielded(self):
        return self.shield_timer > 0

    def update(self, dt, target_pos, projectiles):
        if self.descending:
            self.pos.y = min(self.target_y, self.pos.y + BOSS_DESCEND_SPEED * dt)
            if self.pos.y >= self.target_y:
                self.descending = False
            return False

        direction = target_pos - self.pos
        if direction.length_squared() > 0:
            direction.normalize_ip()
            self.facing = direction
            self.pos += direction * BOSS_SPEED * dt

        if self.teleport_flash > 0:
            self.teleport_flash = max(0.0, self.teleport_flash - dt)

        self.teleport_timer -= dt
        if self.teleport_timer <= 0:
            self.teleport_timer = random.uniform(BOSS_TELEPORT_INTERVAL_MIN, BOSS_TELEPORT_INTERVAL_MAX)
            self.pos.x = random.uniform(ARENA.left + BOSS_RADIUS, ARENA.right - BOSS_RADIUS)
            self.pos.y = random.uniform(ARENA.top + BOSS_RADIUS, ARENA.bottom - BOSS_RADIUS)
            self.teleport_flash = 0.3

        if self.shield_timer > 0:
            self.shield_timer = max(0.0, self.shield_timer - dt)
        else:
            self.shield_roll_timer -= dt
            if self.shield_roll_timer <= 0:
                self.shield_roll_timer = BOSS_SHIELD_ROLL_INTERVAL
                if random.random() < BOSS_SHIELD_CHANCE:
                    self.shield_timer = BOSS_SHIELD_DURATION

        self.ring_timer -= dt
        if self.ring_timer <= 0:
            self.ring_timer = random.uniform(BOSS_RING_INTERVAL_MIN, BOSS_RING_INTERVAL_MAX)
            self._fire_ring(projectiles)
            return True
        return False

    def _fire_ring(self, projectiles):
        for i in range(BOSS_RING_PROJECTILE_COUNT):
            angle = (2 * math.pi / BOSS_RING_PROJECTILE_COUNT) * i
            direction = pygame.Vector2(math.cos(angle), math.sin(angle))
            projectiles.append(BossProjectile(self.pos, direction))

    def draw(self, surface):
        _draw_shadow(surface, self.pos, BOSS_RADIUS * 1.1, BOSS_RADIUS * 0.5)
        if self.teleport_flash > 0:
            t = self.teleport_flash / 0.3
            radius = BOSS_RADIUS + int(40 * (1 - t))
            size = radius * 2 + 8
            flash_surf = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(flash_surf, (*BOSS_COLOR, int(220 * t)), (size // 2, size // 2), radius, 4)
            surface.blit(flash_surf, flash_surf.get_rect(center=self.pos))
        if self.shielded:
            radius = BOSS_RADIUS + 14
            shield_surf = _build_shield_surf(radius * 2 + 8, radius, SHIELD_COLOR)
            surface.blit(shield_surf, shield_surf.get_rect(center=self.pos))

        # Four arms, each ending in a gun, drawn behind the body so the shoulder
        # joins are hidden under its edge.
        for angle_deg in (45, 135, 225, 315):
            arm_dir = pygame.Vector2(1, 0).rotate(angle_deg)
            shoulder = self.pos + arm_dir * (BOSS_RADIUS * 0.75)
            hand = self.pos + arm_dir * (BOSS_RADIUS * 1.3)
            gun_tip = self.pos + arm_dir * (BOSS_RADIUS * 2.15)
            pygame.draw.line(surface, OUTLINE_COLOR, shoulder, hand, 13)
            pygame.draw.line(surface, BOSS_ARM_COLOR, shoulder, hand, 9)
            pygame.draw.line(surface, GUN_COLOR, hand, gun_tip, 7)
            pygame.draw.circle(surface, GUN_GRIP_COLOR, hand, 8)
            pygame.draw.circle(surface, OUTLINE_COLOR, hand, 8, 2)

        pygame.draw.circle(surface, BOSS_COLOR, self.pos, BOSS_RADIUS)
        pygame.draw.circle(surface, OUTLINE_COLOR, self.pos, BOSS_RADIUS, 3)

        # Big scary mouth, fixed at the bottom of the body, full of jagged teeth.
        mouth_w, mouth_h = BOSS_RADIUS * 1.1, BOSS_RADIUS * 0.55
        mouth_rect = pygame.Rect(0, 0, mouth_w, mouth_h)
        mouth_rect.center = (self.pos.x, self.pos.y + BOSS_RADIUS * 0.45)
        pygame.draw.ellipse(surface, BOSS_MOUTH_COLOR, mouth_rect)
        tooth_count = 6
        tooth_w = mouth_w / tooth_count
        for i in range(tooth_count):
            tx = mouth_rect.left + tooth_w * (i + 0.5)
            points = [(tx - tooth_w * 0.35, mouth_rect.top + 2),
                      (tx + tooth_w * 0.35, mouth_rect.top + 2),
                      (tx, mouth_rect.top + mouth_h * 0.55)]
            pygame.draw.polygon(surface, BOSS_TEETH_COLOR, points)
        pygame.draw.ellipse(surface, OUTLINE_COLOR, mouth_rect, 2)

        # One large yellow eye, sliding toward whatever it's chasing.
        eye_center = self.pos + self.facing * (BOSS_RADIUS * 0.3) - pygame.Vector2(0, BOSS_RADIUS * 0.25)
        eye_radius = BOSS_RADIUS * 0.42
        pygame.draw.circle(surface, BOSS_EYE_COLOR, eye_center, eye_radius)
        pygame.draw.circle(surface, OUTLINE_COLOR, eye_center, eye_radius, 2)
        pupil_center = eye_center + self.facing * (eye_radius * 0.4)
        pygame.draw.circle(surface, BOSS_PUPIL_COLOR, pupil_center, eye_radius * 0.45)

        bar_w = BOSS_RADIUS * 2
        bar_h = 8
        bar_x = self.pos.x - BOSS_RADIUS
        bar_y = self.pos.y - BOSS_RADIUS - 20
        pygame.draw.rect(surface, (40, 16, 14), (bar_x, bar_y, bar_w, bar_h))
        hp_ratio = max(0.0, self.hp / BOSS_HP)
        pygame.draw.rect(surface, (210, 90, 50), (bar_x, bar_y, bar_w * hp_ratio, bar_h))


class PowerUp:
    def __init__(self):
        self.pos = pygame.Vector2(
            random.uniform(ARENA.left + POWERUP_RADIUS, ARENA.right - POWERUP_RADIUS),
            random.uniform(ARENA.top + POWERUP_RADIUS, ARENA.bottom - POWERUP_RADIUS),
        )

    def draw(self, surface):
        _draw_shadow(surface, self.pos, POWERUP_RADIUS * 1.1, POWERUP_RADIUS * 0.5)
        glow_radius = POWERUP_RADIUS + 10
        glow_surf = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*POWERUP_COLOR, 70), (glow_radius, glow_radius), glow_radius)
        surface.blit(glow_surf, glow_surf.get_rect(center=self.pos))
        pygame.draw.circle(surface, POWERUP_COLOR, self.pos, POWERUP_RADIUS)
        pygame.draw.circle(surface, OUTLINE_COLOR, self.pos, POWERUP_RADIUS, 2)
        arm = POWERUP_RADIUS * 0.5
        pygame.draw.line(surface, (250, 250, 240), self.pos + (-arm, 0), self.pos + (arm, 0), 3)
        pygame.draw.line(surface, (250, 250, 240), self.pos + (0, -arm), self.pos + (0, arm), 3)


class Game:
    def __init__(self):
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.init()
        pygame.display.set_caption("Superhero vs. Enemies")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 28)
        self.big_font = pygame.font.SysFont("consolas", 56, bold=True)
        self.sounds = sounds.build_sounds()

        self.world_surface = pygame.Surface((WIDTH, HEIGHT)).convert()
        self.vignette_surf = _build_vignette_surface(WIDTH, HEIGHT)
        self.torch_glow_surf = _build_torch_glow(TORCH_RADIUS, TORCH_COLOR)
        self.floor_surface = _build_arena_floor()

        # Torches mounted flush on the arena walls, bracket pointing inward, spread along all
        # four sides like a dungeon corridor rather than a single glow in each corner.
        rng = random.Random(3)
        self.torches = [
            {"pos": (ARENA.left + ARENA.width * 0.28, ARENA.top), "dir": (0, 1), "phase": rng.uniform(0, 6.28)},
            {"pos": (ARENA.left + ARENA.width * 0.72, ARENA.top), "dir": (0, 1), "phase": rng.uniform(0, 6.28)},
            {"pos": (ARENA.left + ARENA.width * 0.28, ARENA.bottom), "dir": (0, -1), "phase": rng.uniform(0, 6.28)},
            {"pos": (ARENA.left + ARENA.width * 0.72, ARENA.bottom), "dir": (0, -1), "phase": rng.uniform(0, 6.28)},
            {"pos": (ARENA.left, ARENA.top + ARENA.height * 0.32), "dir": (1, 0), "phase": rng.uniform(0, 6.28)},
            {"pos": (ARENA.left, ARENA.top + ARENA.height * 0.68), "dir": (1, 0), "phase": rng.uniform(0, 6.28)},
            {"pos": (ARENA.right, ARENA.top + ARENA.height * 0.32), "dir": (-1, 0), "phase": rng.uniform(0, 6.28)},
            {"pos": (ARENA.right, ARENA.top + ARENA.height * 0.68), "dir": (-1, 0), "phase": rng.uniform(0, 6.28)},
        ]

        self.joystick = JoystickReader()
        if not self.joystick.connected:
            print("[game] Joystick not connected - using keyboard fallback.")

        self.reset()

    def reset(self):
        self.player = Player()
        self.bullets = []
        self.enemies = []
        self.powerups = []
        self.score = 0
        self.spawn_timer = SPAWN_INTERVAL_START
        self.powerup_timer = POWERUP_SPAWN_INTERVAL
        self.shoot_cooldown = 0.0
        self.shield_ready_timer = SHIELD_COOLDOWN
        self.shield_available = False
        self.game_over = False
        self.win = False
        self.win_timer = 0.0
        self.elapsed = 0.0
        self.boss = None
        self.boss_spawned = False
        self.boss_projectiles = []
        self._prev_button = False
        self._prev_shield_button = False
        self.joystick.send("Ready, Go!")

    def activate_shield(self):
        if self.shield_available and not self.game_over:
            self.shield_available = False
            self.player.shield_timer = SHIELD_DURATION
            self.shield_ready_timer = SHIELD_COOLDOWN
            self.joystick.send("Shield!")
            self.sounds["shield"].play()

    def spawn_interval(self):
        return max(SPAWN_INTERVAL_MIN, SPAWN_INTERVAL_START - self.score * 0.03)

    def handle_input(self, dt, keys):
        jx, jy, jbtn, jshoot, jshield = self.joystick.read()

        kx = (1 if keys[pygame.K_RIGHT] or keys[pygame.K_d] else 0) - \
             (1 if keys[pygame.K_LEFT] or keys[pygame.K_a] else 0)
        ky = (1 if keys[pygame.K_DOWN] or keys[pygame.K_s] else 0) - \
             (1 if keys[pygame.K_UP] or keys[pygame.K_w] else 0)

        move_x = jx if jx != 0 else kx
        move_y = jy if jy != 0 else ky

        shoot_held = jshoot or keys[pygame.K_SPACE]
        self._prev_button = jbtn

        if jshield and not self._prev_shield_button:
            self.activate_shield()
        self._prev_shield_button = jshield

        if not self.game_over:
            self.player.update(dt, move_x, move_y)

            self.shoot_cooldown = max(0.0, self.shoot_cooldown - dt)
            if shoot_held and self.shoot_cooldown <= 0:
                self.bullets.append(Bullet(self.player.pos, self.player.facing))
                self.shoot_cooldown = SHOOT_COOLDOWN
                self.sounds["shoot"].play()

    def update(self, dt):
        if self.game_over or self.win:
            return

        self.elapsed += dt
        if not self.boss_spawned and self.elapsed >= BOSS_TRIGGER_TIME:
            self.boss_spawned = True
            self.enemies = []
            self.boss = Boss()
            self.joystick.send("Boss!")

        if not self.boss_spawned:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.enemies.append(Enemy())
                self.spawn_timer = self.spawn_interval()

        for bullet in self.bullets:
            bullet.update(dt)
        self.bullets = [b for b in self.bullets if not b.offscreen()]

        for enemy in self.enemies:
            enemy.update(dt, self.player.pos)

        surviving_enemies = []
        for enemy in self.enemies:
            hit = False
            for bullet in self.bullets:
                if enemy.pos.distance_to(bullet.pos) < ENEMY_RADIUS + BULLET_RADIUS:
                    hit = True
                    if bullet in self.bullets:
                        self.bullets.remove(bullet)
                    break
            if hit:
                self.score += 1
            else:
                surviving_enemies.append(enemy)
        self.enemies = surviving_enemies

        remaining_enemies = []
        for enemy in self.enemies:
            if enemy.pos.distance_to(self.player.pos) < ENEMY_RADIUS + PLAYER_RADIUS:
                if self.player.hit():
                    self.sounds["damage"].play()
            else:
                remaining_enemies.append(enemy)
        self.enemies = remaining_enemies

        if self.boss is not None:
            if self.boss.update(dt, self.player.pos, self.boss_projectiles):
                self.sounds["boss_shoot"].play()

            remaining_bullets = []
            for bullet in self.bullets:
                if bullet.pos.distance_to(self.boss.pos) < BOSS_RADIUS + BULLET_RADIUS:
                    if not self.boss.shielded:
                        self.boss.hp -= 1
                        if self.boss.hp <= 0 and not self.win:
                            self.win = True
                            self.win_timer = WIN_LINGER_TIME
                            self.joystick.send("You Win!")
                            self.sounds["you_win"].play()
                else:
                    remaining_bullets.append(bullet)
            self.bullets = remaining_bullets

            if self.boss.pos.distance_to(self.player.pos) < BOSS_RADIUS + PLAYER_RADIUS:
                if self.player.hit():
                    self.sounds["damage"].play()

        for projectile in self.boss_projectiles:
            projectile.update(dt)
        self.boss_projectiles = [p for p in self.boss_projectiles if not p.offscreen()]

        remaining_projectiles = []
        for projectile in self.boss_projectiles:
            if projectile.pos.distance_to(self.player.pos) < ENEMY_RADIUS + PLAYER_RADIUS:
                if self.player.hit():
                    self.sounds["damage"].play()
            else:
                remaining_projectiles.append(projectile)
        self.boss_projectiles = remaining_projectiles

        self.powerup_timer -= dt
        if self.powerup_timer <= 0:
            self.powerups.append(PowerUp())
            self.powerup_timer = POWERUP_SPAWN_INTERVAL

        remaining_powerups = []
        for powerup in self.powerups:
            if powerup.pos.distance_to(self.player.pos) < POWERUP_RADIUS + PLAYER_RADIUS:
                self.player.lives = min(PLAYER_MAX_LIVES, self.player.lives + POWERUP_HEAL_AMOUNT)
                self.joystick.send("Health Up!")
                self.sounds["health_up"].play()
            else:
                remaining_powerups.append(powerup)
        self.powerups = remaining_powerups

        if not self.shield_available:
            self.shield_ready_timer -= dt
            if self.shield_ready_timer <= 0:
                self.shield_available = True

        if self.player.lives <= 0 and not self.game_over and not self.win:
            self.game_over = True
            self.joystick.send("Game Over")
            self.sounds["game_over"].play()

    def draw(self):
        world = self.world_surface
        world.fill(BG_COLOR)
        world.blit(self.floor_surface, ARENA.topleft)
        pygame.draw.rect(world, ARENA_BORDER, ARENA, 4)

        for torch in self.torches:
            self._draw_torch(world, torch)

        for bullet in self.bullets:
            bullet.draw(world)
        for powerup in self.powerups:
            powerup.draw(world)
        for enemy in self.enemies:
            enemy.draw(world)
        for projectile in self.boss_projectiles:
            projectile.draw(world)
        if self.boss is not None:
            self.boss.draw(world)
        self.player.draw(world)

        # Downscale then upscale for a chunky pixel-art look, then composite onto the real screen.
        small = pygame.transform.scale(world, (WIDTH // PIXEL_SCALE, HEIGHT // PIXEL_SCALE))
        pygame.transform.scale(small, (WIDTH, HEIGHT), self.screen)
        self.screen.blit(self.vignette_surf, (0, 0))

        self._draw_panel_text(f"Score: {self.score}", (12, 10))

        lives_text = "Lives: " + " ".join("*" for _ in range(max(0, self.player.lives)))
        lives_surf = self.font.render(lives_text, True, TEXT_COLOR)
        panel_w = lives_surf.get_width() + 12
        self._draw_panel_text(lives_text, (WIDTH - 12 - panel_w, 10))

        conn_text = "Joystick: connected" if self.joystick.connected else "Joystick: keyboard fallback"
        self._draw_panel_text(conn_text, (12, HEIGHT - 42), color=(190, 170, 140))

        if self.shield_available:
            self.draw_shield_icon((WIDTH // 2, 34))

        if self.game_over:
            over_surf = self.big_font.render("GAME OVER", True, (220, 70, 60))
            self.screen.blit(over_surf, over_surf.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30)))
            hint_surf = self.font.render(
                "Press R or the joystick button to restart", True, TEXT_COLOR,
            )
            self.screen.blit(hint_surf, hint_surf.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30)))

        if self.win:
            win_surf = self.big_font.render("YOU WIN", True, WIN_COLOR)
            self.screen.blit(win_surf, win_surf.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30)))
            if self.win_timer > 0:
                hint_text = f"Restart available in {self.win_timer:.1f}s"
            else:
                hint_text = "Press R or the joystick button to restart"
            hint_surf = self.font.render(hint_text, True, WIN_COLOR)
            self.screen.blit(hint_surf, hint_surf.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30)))

        pygame.display.flip()

    def _draw_torch(self, surface, torch):
        pos = torch["pos"]
        dx, dy = torch["dir"]
        flicker = 0.85 + 0.15 * math.sin(pygame.time.get_ticks() * 0.006 + torch["phase"])

        bracket_end = (pos[0] + dx * TORCH_BRACKET_LENGTH, pos[1] + dy * TORCH_BRACKET_LENGTH)
        pygame.draw.line(surface, (40, 28, 20), pos, bracket_end, 6)
        pygame.draw.circle(surface, (30, 20, 15), pos, 6)

        flame_pos = (pos[0] + dx * TORCH_FLAME_OFFSET, pos[1] + dy * TORCH_FLAME_OFFSET)
        pygame.draw.circle(surface, (200, 90, 30), flame_pos, 9 * flicker)
        pygame.draw.circle(surface, (255, 190, 80), flame_pos, 5 * flicker)

        glow_rect = self.torch_glow_surf.get_rect(center=flame_pos)
        surface.blit(self.torch_glow_surf, glow_rect, special_flags=pygame.BLEND_ADD)

    def _draw_panel_text(self, text, topleft, color=TEXT_COLOR, padding=6):
        text_surf = self.font.render(text, True, color)
        panel = pygame.Surface(
            (text_surf.get_width() + padding * 2, text_surf.get_height() + padding * 2),
            pygame.SRCALPHA,
        )
        panel.fill((12, 9, 7, 175))
        pygame.draw.rect(panel, (90, 55, 38, 220), panel.get_rect(), 2)
        self.screen.blit(panel, topleft)
        self.screen.blit(text_surf, (topleft[0] + padding, topleft[1] + padding))

    def draw_shield_icon(self, center):
        cx, cy = center
        points = [
            (cx, cy - 16), (cx + 13, cy - 8), (cx + 13, cy + 6),
            (cx, cy + 18), (cx - 13, cy + 6), (cx - 13, cy - 8),
        ]
        pygame.draw.polygon(self.screen, SHIELD_COLOR, points)
        pygame.draw.polygon(self.screen, (20, 60, 90), points, 2)
        hint_surf = self.font.render("Shield ready! [E]", True, SHIELD_COLOR)
        self.screen.blit(hint_surf, hint_surf.get_rect(midtop=(cx, cy + 24)))

    def run(self):
        while True:
            dt = self.clock.tick(60) / 1000.0

            if self.win and self.win_timer > 0:
                self.win_timer = max(0.0, self.win_timer - dt)
            restart_allowed = self.game_over or (self.win and self.win_timer <= 0)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit()
                    if event.key == pygame.K_r and restart_allowed:
                        self.reset()
                    if event.key == pygame.K_e:
                        self.activate_shield()

            keys = pygame.key.get_pressed()

            if self.game_over or self.win:
                _, _, jbtn, jshoot, _ = self.joystick.read()
                if restart_allowed and (jbtn or jshoot) and not self._prev_button:
                    self.reset()
                self._prev_button = jbtn or jshoot
            else:
                self.handle_input(dt, keys)
                self.update(dt)

            self.draw()


if __name__ == "__main__":
    Game().run()
