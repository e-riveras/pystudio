# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately
through GitHub: the **Security** tab of this repository, then **Report a
vulnerability**. You should hear back within a week.

Only the latest release is supported with fixes.

## What is worth knowing

- **The kernel.** pystudio starts its Jupyter kernel on Unix domain sockets in a
  directory only your user can enter, not on TCP ports. Code you send runs with
  your own permissions, as it would in any Python session.
- **The assistant** (`--assistant`, off by default) sends your request, the
  buffer's text and whatever it inspects in the kernel to Anthropic's API.
  Nothing is sent until you ask it something.
- **The agent pane** (`--agent`, off by default) runs Claude Code's own command
  line program. pystudio gives it a read-only view of the kernel through a Unix
  socket in a private directory.
- **Opening a figure outside pystudio** (`o`, `y`) writes it to a private
  directory under the system's temporary directory, which pystudio does not
  remove.
