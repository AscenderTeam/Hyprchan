// One conversation: user turns preempt observations; observations never backlog.
export class TurnQueue {
  constructor(run, onError) {
    this.run = run;
    this.onError = onError;
    this.chats = [];
    this.reaction = null;
    this.active = null;
    this.closed = false;
  }

  submit(command) {
    if (this.closed) return;
    if (command.type === 'chat') {
      this.cancelReactions();
      this.chats.push(command);
    } else {
      this.reaction = command;
    }
    this.drain();
  }

  cancelReactions() {
    this.reaction = null;
    if (this.active?.command.type === 'react') this.active.controller.abort();
  }

  drain() {
    if (this.closed || this.active) return;
    const command = this.chats.shift() || this.reaction;
    if (!command) return;
    if (command.type === 'react') this.reaction = null;
    const controller = new AbortController();
    const active = { command, controller, promise: null };
    this.active = active;
    active.promise = Promise.resolve().then(() => this.run(command, controller.signal))
      .catch(error => this.onError(error, command))
      .finally(() => {
        this.active = null;
        this.drain();
      });
  }

  async close() {
    this.closed = true;
    this.chats = [];
    this.reaction = null;
    this.active?.controller.abort();
    await this.active?.promise;
  }
}
