"""Opt-in, bounded visual preview for the Uncrashed ANGLE simulator pilot.

No gate identity/depth is inferred. A stable smaller magenta opening is only a
candidate for the next gate; current-gate containment and existing guidance win.
"""
import math


class GatePreview:
    def __init__(self):
        self.reset()

    def reset(self):
        self.target = None
        self.since = self.last_t = self.pass_count = None

    def apply(self, pilot, command, gate, future, now):
        c = pilot.cfg
        command.preview_yaw = command.preview_roll = 0.0
        command.preview_target_x = None
        command.preview_reason = 'disabled'
        if not c.get('gate_preview', 0):
            self.reset()
            return command

        def reject(reason):
            self.reset()
            command.preview_reason = reason
            return command

        if (command.abort or command.done or command.state != 'approach' or pilot.blind
                or command.pitch*c['forward_sign'] <= .05):
            return reject('guidance_priority')
        if (not pilot.valid_gate(gate) or gate.clipped or not .08 <= gate.size <= .35
                or abs(gate.x) > min(.12, c['alignment_x']*.4)
                or not pilot._frames_path(gate, pilot.aim())):
            return reject('current_gate_not_clear')
        x0, y0, x1, y1 = gate.bbox
        if not all(math.isfinite(v) for v in gate.bbox) or x1 <= x0 or y1 <= y0:
            return reject('invalid_opening')
        # A future gate must be smaller and visible through the protected current opening.
        mx, my = .25*(x1-x0), .2*(y1-y0)
        choices = [g for g in future if pilot.valid_gate(g) and not g.clipped
                   and .02 <= g.size <= .75*gate.size
                   and x0+mx < g.x < x1-mx and y0+my < g.y < y1-my]
        choices.sort(key=lambda g: g.size, reverse=True)
        if not choices:
            return reject('no_contained_future_gate')
        if len(choices)>1 and choices[1].size > .8*choices[0].size:
            return reject('ambiguous_future_gate')
        target = choices[0]
        if (self.target is None or self.pass_count != command.passes or self.last_t is None
                or now <= self.last_t or now-self.last_t > c['max_frame_age_s']
                or math.hypot(target.x-self.target[0], target.y-self.target[1]) > .12
                or not .65 <= target.size/self.target[2] <= 1.5):
            self.since = now
        self.target = (target.x, target.y, target.size)
        self.last_t, self.pass_count = now, command.passes
        command.preview_target_x = target.x
        if now-self.since < .2:
            command.preview_reason = 'confirming_future_gate'
            return command
        ramp = min(1., (now-self.since-.2)/.3)
        # At most 10% of opening width, and never outside its central corridor.
        shift = max(-.06, min(.06, .2*(target.x-gate.x)))
        shift = max(-.1*(x1-x0), min(.1*(x1-x0), shift))
        delta = c['yaw_sign']*max(-.025, min(.025, c['yaw_kp']*shift))*ramp
        if abs(command.yaw)>.015 and command.yaw*delta<0:
            return reject('current_correction_priority')
        old_yaw, old_roll = command.yaw, command.roll
        command.yaw = max(-c['max_yaw'], min(c['max_yaw'], old_yaw+delta))
        bank_delta = c['roll_sign']*c['bank_per_yaw']*delta*c['yaw_sign']
        bank_delta = max(-.02, min(.02, bank_delta))
        # Do not shrink an existing roll command when already outside max_bank.
        limit = max(abs(old_roll), c['max_bank'])
        command.roll = max(-limit, min(limit, old_roll+bank_delta))
        command.preview_yaw = command.yaw-old_yaw
        command.preview_roll = command.roll-old_roll
        command.preview_reason = 'active'
        return command
