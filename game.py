"""Superhero vs. Enemies - a simple 2D shooter controlled by an Arduino joystick.

Controls:
  Joystick             - move the hero around the arena
  External shoot button - shoot in the direction you're facing
  Joystick button       - restart after game over
  (Fallback) WASD/Arrows to move, Space to shoot, R to restart, Esc to quit.
"""

import math
import random
import sys

import pygame

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

BG_COLOR = (18, 20, 28)
ARENA_COLOR = (34, 38, 52)
ARENA_BORDER = (90, 100, 140)
HERO_BODY = (60, 130, 246)
HERO_CAPE = (220, 50, 50)
BULLET_COLOR = (250, 220, 90)
ENEMY_COLOR = (200, 60, 90)
POWERUP_COLOR = (80, 220, 120)
TEXT_COLOR = (235, 235, 240)


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


class Player:
    def __init__(self):
        self.pos = pygame.Vector2(ARENA.centerx, ARENA.centery)
        self.facing = pygame.Vector2(0, -1)
        self.lives = PLAYER_MAX_LIVES
        self.invulnerable = 0.0

    def update(self, dt, move_x, move_y):
        move = pygame.Vector2(move_x, move_y)
        if move.length_squared() > 0:
            if move.length() > 1:
                move.scale_to_length(1)
            self.facing = move.normalize()
            self.pos += move * PLAYER_SPEED * dt

        self.pos.x = clamp(self.pos.x, ARENA.left + PLAYER_RADIUS, ARENA.right - PLAYER_RADIUS)
        self.pos.y = clamp(self.pos.y, ARENA.top + PLAYER_RADIUS, ARENA.bottom - PLAYER_RADIUS)

        if self.invulnerable > 0:
            self.invulnerable = max(0.0, self.invulnerable - dt)

    def hit(self):
        if self.invulnerable <= 0:
            self.lives -= 1
            self.invulnerable = INVULNERABLE_TIME
            return True
        return False

    def draw(self, surface):
        flashing = self.invulnerable > 0 and int(self.invulnerable * 10) % 2 == 0
        if flashing:
            return
        cape_tip = self.pos - self.facing * (PLAYER_RADIUS * 2.2)
        side = pygame.Vector2(-self.facing.y, self.facing.x)
        cape_a = self.pos + side * PLAYER_RADIUS * 0.8
        cape_b = self.pos - side * PLAYER_RADIUS * 0.8
        pygame.draw.polygon(surface, HERO_CAPE, [cape_a, cape_b, cape_tip])
        pygame.draw.circle(surface, HERO_BODY, self.pos, PLAYER_RADIUS)
        eye_offset = self.facing * (PLAYER_RADIUS * 0.5)
        pygame.draw.circle(surface, (255, 255, 255), self.pos + eye_offset, 4)


class Bullet:
    def __init__(self, pos, direction):
        self.pos = pygame.Vector2(pos)
        self.vel = direction * BULLET_SPEED

    def update(self, dt):
        self.pos += self.vel * dt

    def offscreen(self):
        return not ARENA.inflate(40, 40).collidepoint(self.pos)

    def draw(self, surface):
        pygame.draw.circle(surface, BULLET_COLOR, self.pos, BULLET_RADIUS)


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
        pygame.draw.circle(surface, ENEMY_COLOR, self.pos, ENEMY_RADIUS)
        pygame.draw.circle(surface, (30, 10, 15), self.pos, ENEMY_RADIUS, 2)


class PowerUp:
    def __init__(self):
        self.pos = pygame.Vector2(
            random.uniform(ARENA.left + POWERUP_RADIUS, ARENA.right - POWERUP_RADIUS),
            random.uniform(ARENA.top + POWERUP_RADIUS, ARENA.bottom - POWERUP_RADIUS),
        )

    def draw(self, surface):
        pygame.draw.circle(surface, POWERUP_COLOR, self.pos, POWERUP_RADIUS)
        pygame.draw.circle(surface, (20, 60, 30), self.pos, POWERUP_RADIUS, 2)
        arm = POWERUP_RADIUS * 0.5
        pygame.draw.line(surface, (255, 255, 255), self.pos + (-arm, 0), self.pos + (arm, 0), 3)
        pygame.draw.line(surface, (255, 255, 255), self.pos + (0, -arm), self.pos + (0, arm), 3)


class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Superhero vs. Enemies")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 28)
        self.big_font = pygame.font.SysFont("consolas", 56, bold=True)

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
        self.game_over = False
        self._prev_button = False

    def spawn_interval(self):
        return max(SPAWN_INTERVAL_MIN, SPAWN_INTERVAL_START - self.score * 0.03)

    def handle_input(self, dt, keys):
        jx, jy, jbtn, jshoot = self.joystick.read()

        kx = (1 if keys[pygame.K_RIGHT] or keys[pygame.K_d] else 0) - \
             (1 if keys[pygame.K_LEFT] or keys[pygame.K_a] else 0)
        ky = (1 if keys[pygame.K_DOWN] or keys[pygame.K_s] else 0) - \
             (1 if keys[pygame.K_UP] or keys[pygame.K_w] else 0)

        move_x = jx if jx != 0 else kx
        move_y = jy if jy != 0 else ky

        shoot_held = jshoot or keys[pygame.K_SPACE]
        self._prev_button = jbtn

        if not self.game_over:
            self.player.update(dt, move_x, move_y)

            self.shoot_cooldown = max(0.0, self.shoot_cooldown - dt)
            if shoot_held and self.shoot_cooldown <= 0:
                self.bullets.append(Bullet(self.player.pos, self.player.facing))
                self.shoot_cooldown = SHOOT_COOLDOWN

    def update(self, dt):
        if self.game_over:
            return

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
                self.player.hit()
            else:
                remaining_enemies.append(enemy)
        self.enemies = remaining_enemies

        self.powerup_timer -= dt
        if self.powerup_timer <= 0:
            self.powerups.append(PowerUp())
            self.powerup_timer = POWERUP_SPAWN_INTERVAL

        remaining_powerups = []
        for powerup in self.powerups:
            if powerup.pos.distance_to(self.player.pos) < POWERUP_RADIUS + PLAYER_RADIUS:
                self.player.lives = min(PLAYER_MAX_LIVES, self.player.lives + POWERUP_HEAL_AMOUNT)
            else:
                remaining_powerups.append(powerup)
        self.powerups = remaining_powerups

        if self.player.lives <= 0:
            self.game_over = True

    def draw(self):
        self.screen.fill(BG_COLOR)
        pygame.draw.rect(self.screen, ARENA_COLOR, ARENA)
        pygame.draw.rect(self.screen, ARENA_BORDER, ARENA, 3)

        for bullet in self.bullets:
            bullet.draw(self.screen)
        for powerup in self.powerups:
            powerup.draw(self.screen)
        for enemy in self.enemies:
            enemy.draw(self.screen)
        self.player.draw(self.screen)

        score_surf = self.font.render(f"Score: {self.score}", True, TEXT_COLOR)
        self.screen.blit(score_surf, (16, 12))

        lives_text = "Lives: " + " ".join("*" for _ in range(max(0, self.player.lives)))
        lives_surf = self.font.render(lives_text, True, TEXT_COLOR)
        self.screen.blit(lives_surf, (WIDTH - lives_surf.get_width() - 16, 12))

        conn_text = "Joystick: connected" if self.joystick.connected else "Joystick: keyboard fallback"
        conn_surf = self.font.render(conn_text, True, (140, 150, 170))
        self.screen.blit(conn_surf, (16, HEIGHT - 34))

        if self.game_over:
            over_surf = self.big_font.render("GAME OVER", True, (255, 90, 90))
            self.screen.blit(over_surf, over_surf.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 30)))
            hint_surf = self.font.render(
                "Press R or the joystick button to restart", True, TEXT_COLOR,
            )
            self.screen.blit(hint_surf, hint_surf.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30)))

        pygame.display.flip()

    def run(self):
        while True:
            dt = self.clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit()
                    if event.key == pygame.K_r and self.game_over:
                        self.reset()

            keys = pygame.key.get_pressed()

            if self.game_over:
                _, _, jbtn, jshoot = self.joystick.read()
                if (jbtn or jshoot) and not self._prev_button:
                    self.reset()
                self._prev_button = jbtn or jshoot
            else:
                self.handle_input(dt, keys)
                self.update(dt)

            self.draw()


if __name__ == "__main__":
    Game().run()
