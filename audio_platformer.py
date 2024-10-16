import pygame
import random
import math
import pyaudio
import wave
import audioop
import time
import requests
import json
from collections import deque
import threading

# Constants
WIDTH, HEIGHT = 1200, 700
GRAVITY = 0.65
MIN_PLATFORM_WIDTH, MAX_PLATFORM_WIDTH = 100, 300
MIN_GAP_WIDTH, MAX_GAP_WIDTH = 45, 200
MAX_HEIGHT_DIFFERENCE = 100
MIN_PLATFORM_HEIGHT = 75
MOVING_PLATFORM_BUFFER = 80
SINKING_PLATFORM_SCORE = 20
MOVING_PLATFORM_SCORE = 40
DIFFICULTY_INCREASE_INTERVAL = 20

# Audio Constants
CHUNK, FORMAT, CHANNELS, RATE = 1024, pyaudio.paInt16, 1, 16000
SILENCE_THRESHOLD, SILENCE_DURATION, AMPLIFICATION = 250, 0.9, 8
PRE_BUFFER_SIZE = 10
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen?smart_format=true&model=nova-2&language=en-US"
DEEPGRAM_KEY = ""  # Replace with your actual API key

# Colors
COLORS = {
    'background': (224, 224, 224),
    'player': (74, 74, 74),
    'player_charged': (140, 110, 9),
    'static_platform': (109, 109, 109),
    'moving_platform': (90, 125, 154),
    'sinking_platform': (154, 90, 90),
    'text': (50, 50, 50),
    'highlight': (255, 165, 0)
}

class AudioProcessor(threading.Thread):
    def __init__(self, game):
        threading.Thread.__init__(self)
        self.game = game
        self.daemon = True
        self.running = True
        print("AudioProcessor initialized")

    def run(self):
        print("AudioProcessor thread started")
        while self.running:
            if not self.game.player.is_jumping and not self.game.player.is_charging:
                print("Player ready for audio input")
                audio_file = self.save_audio(self.record_audio())
                print(f"Audio saved to {audio_file}")
                transcript = self.transcribe_audio(audio_file)
                if transcript:
                    print(f"Transcription: {transcript}")
                    jump_count = self.count_consecutive_jumps(transcript)
                    print(f"Detected {jump_count} consecutive jumps")
                    self.game.set_transcript(transcript, jump_count)
                    self.game.player.audio_jump(jump_count)
                else:
                    print("Transcription failed or returned None")
            else:
                print("Player is jumping or charging, skipping audio input")
            time.sleep(0.1)  # Short sleep to prevent CPU overuse
        print("AudioProcessor thread stopped")

    def record_audio(self):
        print("Starting audio recording")
        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        
        frames, silent_chunks, is_recording = [], 0, False
        pre_buffer = deque(maxlen=PRE_BUFFER_SIZE)

        while True:
            data = stream.read(CHUNK)
            if not is_recording:
                pre_buffer.append(data)
                if audioop.rms(data, 2) >= SILENCE_THRESHOLD:
                    print("Speech detected, starting recording")
                    is_recording = True
                    frames.extend(pre_buffer)
            else:
                if audioop.rms(data, 2) < SILENCE_THRESHOLD:
                    silent_chunks += 1
                    if silent_chunks > int(SILENCE_DURATION * RATE / CHUNK):
                        print("Silence detected, stopping recording")
                        break
                else:
                    silent_chunks = 0
                frames.append(data)

        stream.stop_stream()
        stream.close()
        p.terminate()
        print("Audio recording finished")
        return audioop.mul(b''.join(frames), 2, AMPLIFICATION)

    def save_audio(self, audio_data, filename="recorded_audio.wav"):
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(pyaudio.PyAudio().get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(audio_data)
        print(f"Audio saved to {filename}")
        return filename

    def transcribe_audio(self, audio_file):
        print(f"Transcribing audio file: {audio_file}")
        with open(audio_file, 'rb') as f:
            response = requests.post(DEEPGRAM_URL, headers={"Authorization": f"Token {DEEPGRAM_KEY}"}, data=f)
        
        if response.status_code == 200:
            transcript = response.json()['results']['channels'][0]['alternatives'][0]['transcript']
            print(f"Transcription successful: {transcript}")
            return transcript
        else:
            print(f"Transcription error: Status code {response.status_code}")
            print(f"Response text: {response.text}")
            return None
        
    def count_consecutive_jumps(self, transcript):
        words = transcript.lower().split()
        print(f"Counting jumps in words: {words}")
        count = 0
        for word in words:
            if word in ["jump", "jump.", "jump,", "chomp", "chomp,", "chomp.", "john", 
                        "john,", "john.", "go", "go,", "go.", "yep", "yep,", "yep."]:
                count += 1
            elif count > 0:
                break
        count = min(count, 10)  # Limit to 10 consecutive jumps
        print(f"Counted {count} consecutive jumps")
        return count

class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = self.original_width = 35
        self.height = self.original_height = 35
        self.speed = 10
        self.jump_force = 0
        self.max_jump_force = 32
        self.charge_rate = 0.55
        self.velocity_y = 0
        self.velocity_x = 0
        self.is_jumping = False
        self.is_charging = False
        self.squeeze_factor = 1.0
        self.rotation = 0
        self.rotation_speed = 0

    def update(self, platforms):
        if self.is_charging and not self.is_jumping:
            self.jump_force = min(self.jump_force + self.charge_rate, self.max_jump_force)
            charge_progress = self.jump_force / self.max_jump_force
            self.squeeze_factor = 1 - (charge_progress * 0.3)
        elif not self.is_charging and self.squeeze_factor < 1.0:
            self.squeeze_factor = min(self.squeeze_factor + 0.1, 1.0)

        self.velocity_y += GRAVITY
        self.y += self.velocity_y
        self.x += self.velocity_x

        if self.is_jumping:
            self.rotation += self.rotation_speed
            self.rotation_speed *= 0.99
        else:
            self.rotation *= 0.8

        on_platform = False
        for platform in platforms:
            if self.check_platform_collision(platform):
                on_platform = True
                self.y = HEIGHT - platform.platform_height - platform.height - self.height
                self.velocity_y = 0
                self.is_jumping = False
                self.velocity_x = 0
                self.rotation = 0

                if platform.is_moving:
                    self.x += platform.move_speed

                if platform.is_sinking:
                    platform.sink_delay -= 16
                    if platform.sink_delay <= 0:
                        platform.height -= platform.sink_speed
                        self.y += platform.sink_speed
                        if platform.height <= -platform.platform_height:
                            on_platform = False
                            self.is_jumping = True

        if not on_platform and not self.is_jumping:
            self.is_jumping = True

        if self.is_jumping:
            self.velocity_x *= 0.995

    def check_platform_collision(self, platform):
        return (self.y + self.height >= HEIGHT - platform.platform_height - platform.height and
                self.y + self.height <= HEIGHT - platform.height and
                self.x + self.width > platform.x and
                self.x < platform.x + platform.width)

    def draw(self, screen):
        squeezed_width = int(self.original_width * (2 - self.squeeze_factor))
        squeezed_height = int(self.original_height * self.squeeze_factor)

        charge_progress = self.jump_force / self.max_jump_force
        r = int(COLORS['player'][0] + (COLORS['player_charged'][0] - COLORS['player'][0]) * charge_progress)
        g = int(COLORS['player'][1] + (COLORS['player_charged'][1] - COLORS['player'][1]) * charge_progress)
        b = int(COLORS['player'][2] + (COLORS['player_charged'][2] - COLORS['player'][2]) * charge_progress)
        player_color = (r, g, b)

        player_surface = pygame.Surface((squeezed_width, squeezed_height), pygame.SRCALPHA)
        pygame.draw.rect(player_surface, player_color, (0, 0, squeezed_width, squeezed_height))

        rotated_surface = pygame.transform.rotate(player_surface, math.degrees(self.rotation))
        new_rect = rotated_surface.get_rect(midbottom=(self.x + self.width//2, self.y + self.height))

        screen.blit(rotated_surface, new_rect.topleft)

    def audio_jump(self, jump_count):
        if not self.is_jumping and not self.is_charging:
            self.is_charging = True
            self.jump_force = (jump_count / 10) * self.max_jump_force
            self.is_charging = False
            self.is_jumping = True
            self.velocity_y = -self.jump_force
            self.velocity_x = self.jump_force * 0.55
            self.jump_force = 0
            self.rotation_speed = -0.1

class Platform:
    def __init__(self, x, width, height, is_sinking=False, is_moving=False):
        self.x = self.original_x = x
        self.width = width
        self.height = self.original_height = height
        self.platform_height = 15 if is_moving else 30
        self.is_sinking = is_sinking
        self.sink_delay = 2100
        self.sink_speed = 1
        self.is_moving = is_moving
        self.move_distance = random.randint(90, MIN_GAP_WIDTH + MOVING_PLATFORM_BUFFER) if is_moving else 0
        self.move_speed = random.choice([-1, 1]) * (random.random() * 1.2 + 0.6) if is_moving else 0
        self.min_x = x
        self.max_x = x + self.move_distance

    def update(self):
        if self.is_moving:
            self.x += self.move_speed
            if self.x <= self.min_x or self.x + self.width >= self.max_x:
                self.move_speed *= -1
                self.x = max(self.min_x, min(self.x, self.max_x - self.width))

    def draw(self, screen):
        color = COLORS['sinking_platform'] if self.is_sinking else COLORS['moving_platform'] if self.is_moving else COLORS['static_platform']
        pygame.draw.rect(screen, color, (self.x, HEIGHT - self.platform_height - self.height, self.width, self.platform_height))

class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Infinite Platformer with Audio Jump")
        self.clock = pygame.time.Clock()
        
        pygame.font.init()
        self.font = pygame.font.Font(None, 36)
        self.large_font = pygame.font.Font(None, 72)
        self.title_font = pygame.font.Font(None, 100)
        
        self.high_score = 0
        self.transcript = ""
        self.jump_count = 0
        self.reset_game()
        self.audio_processor = AudioProcessor(self)
        self.audio_processor.start()

    def reset_game(self):
        self.player = Player(100, 0)
        self.platforms = []
        self.game_over = False
        self.total_distance = 0
        self.difficulty = {'current_level': 0, 'sinking_platform_prob': 0.27, 'moving_platform_prob': 0.27}
        self.generate_initial_platforms()

    def generate_initial_platforms(self):
        self.generate_platform(0, is_first=True)
        while self.platforms[-1].x + self.platforms[-1].width < WIDTH * 2:
            last_platform = self.platforms[-1]
            gap_width = random.randint(MIN_GAP_WIDTH, MAX_GAP_WIDTH)
            self.generate_platform(last_platform.x + last_platform.width + gap_width)

        first_platform = self.platforms[0]
        self.player.x = first_platform.x + first_platform.width // 2 - self.player.width // 2
        self.player.y = HEIGHT - first_platform.platform_height - first_platform.height - self.player.height

    def generate_platform(self, x, is_first=False):
        width = 200 if is_first else random.randint(MIN_PLATFORM_WIDTH, MAX_PLATFORM_WIDTH)
        height = MIN_PLATFORM_HEIGHT if is_first else random.randint(MIN_PLATFORM_HEIGHT, MAX_HEIGHT_DIFFERENCE + MIN_PLATFORM_HEIGHT)
        is_sinking = not is_first and random.random() < self.difficulty['sinking_platform_prob']
        is_moving = not is_first and random.random() < self.difficulty['moving_platform_prob']

        adjusted_width = min(width, MIN_GAP_WIDTH + MOVING_PLATFORM_BUFFER // 2) if is_moving else width
        x = x + MOVING_PLATFORM_BUFFER if is_moving else x

        self.platforms.append(Platform(x, adjusted_width, height, is_sinking, is_moving))

    def update_difficulty(self):
        score = self.total_distance // 100
        new_level = score // DIFFICULTY_INCREASE_INTERVAL
        if new_level > self.difficulty['current_level']:
            self.difficulty['current_level'] = new_level
            self.difficulty['sinking_platform_prob'] = 0.27 + new_level * 0.03
            self.difficulty['moving_platform_prob'] = 0.27 + (new_level - 2) * 0.03 if score >= MOVING_PLATFORM_SCORE else 0

    def update(self):
        if self.game_over:
            return

        self.update_difficulty()
        self.player.update(self.platforms)

        if self.player.velocity_x > 0:
            self.total_distance += self.player.velocity_x

        if self.player.x > WIDTH // 2:
            diff = self.player.x - WIDTH // 2
            self.player.x = WIDTH // 2
            for platform in self.platforms:
                platform.x -= diff
                platform.original_x -= diff
                platform.min_x -= diff
                platform.max_x -= diff

        if self.player.y + self.player.height > HEIGHT:
            self.game_over = True
            return

        for platform in self.platforms:
            platform.update()

        self.platforms = [p for p in self.platforms if p.x + p.width > 0]
        
        if self.platforms[-1].x + self.platforms[-1].width < WIDTH * 2:
            gap_width = random.randint(MIN_GAP_WIDTH, MAX_GAP_WIDTH)
            self.generate_platform(self.platforms[-1].x + self.platforms[-1].width + gap_width)

    def draw(self):
        self.screen.fill(COLORS['background'])

        for platform in self.platforms:
            if platform.x + platform.width > 0 and platform.x < WIDTH:
                platform.draw(self.screen)

        self.player.draw(self.screen)

        self.draw_ui()

        pygame.display.flip()

    def draw_ui(self):
        # Current score
        score = self.total_distance // 100
        score_text = self.font.render(f"Score: {score}", True, COLORS['text'])
        score_rect = score_text.get_rect(topright=(WIDTH - 20, 20))
        self.screen.blit(score_text, score_rect)

        # High score
        high_score_text = self.font.render(f"High Score: {self.high_score}", True, COLORS['text'])
        high_score_rect = high_score_text.get_rect(topright=(WIDTH - 20, 60))
        self.screen.blit(high_score_text, high_score_rect)

        # Difficulty level
        difficulty_text = self.font.render(f"Level: {self.difficulty['current_level']}", True, COLORS['text'])
        difficulty_rect = difficulty_text.get_rect(topleft=(20, 20))
        self.screen.blit(difficulty_text, difficulty_rect)

        # Display transcript
        transcript_text = self.font.render(f"Transcript: {self.transcript}", True, COLORS['text'])
        transcript_rect = transcript_text.get_rect(bottomleft=(20, HEIGHT - 60))
        self.screen.blit(transcript_text, transcript_rect)

        # Display jump count
        jump_count_text = self.font.render(f"Jumps: {self.jump_count}", True, COLORS['highlight'])
        jump_count_rect = jump_count_text.get_rect(bottomleft=(20, HEIGHT - 20))
        self.screen.blit(jump_count_text, jump_count_rect)

        if self.game_over:
            self.draw_game_over()

    def draw_game_over(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))  # Semi-transparent black overlay
        self.screen.blit(overlay, (0, 0))

        game_over_text = self.title_font.render("Game Over", True, COLORS['highlight'])
        game_over_rect = game_over_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 50))
        self.screen.blit(game_over_text, game_over_rect)

        score = self.total_distance // 100
        final_score_text = self.large_font.render(f"Final Score: {score}", True, COLORS['text'])
        final_score_rect = final_score_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 30))
        self.screen.blit(final_score_text, final_score_rect)

        if score > self.high_score:
            new_high_score_text = self.font.render("New High Score!", True, COLORS['highlight'])
            new_high_score_rect = new_high_score_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 80))
            self.screen.blit(new_high_score_text, new_high_score_rect)

        restart_text = self.font.render("Press Up Arrow to Restart", True, COLORS['text'])
        restart_rect = restart_text.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 130))
        self.screen.blit(restart_text, restart_rect)

    def set_transcript(self, transcript, jump_count):
        self.transcript = transcript
        self.jump_count = jump_count

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        if self.game_over:
                            self.high_score = max(self.high_score, self.total_distance // 100)
                            self.reset_game()
                        elif not self.player.is_jumping and not self.player.is_charging:
                            self.player.is_charging = True
                            self.player.jump_force = 0
                elif event.type == pygame.KEYUP:
                    if event.key == pygame.K_UP and self.player.is_charging:
                        self.player.is_charging = False
                        self.player.is_jumping = True
                        self.player.velocity_y = -self.player.jump_force
                        self.player.velocity_x = self.player.jump_force * 0.55
                        self.player.jump_force = 0
                        self.player.rotation_speed = -0.1

            self.update()
            self.draw()
            self.clock.tick(60)

        self.audio_processor.running = False
        self.audio_processor.join()
        pygame.quit()

if __name__ == "__main__":
    game = Game()
    game.run()