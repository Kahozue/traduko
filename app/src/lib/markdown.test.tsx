import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { renderMarkdown } from "./markdown";

function renderMd(source: string) {
  return render(<div>{renderMarkdown(source)}</div>);
}

test("renders bold, italic and inline code", () => {
  renderMd("This is **bold**, _italic_ and `code`.");
  expect(screen.getByText("bold").tagName).toBe("STRONG");
  expect(screen.getByText("italic").tagName).toBe("EM");
  expect(screen.getByText("code").tagName).toBe("CODE");
});

test("renders an unordered list", () => {
  const { container } = renderMd("- one\n- two\n- three");
  const items = container.querySelectorAll("ul li");
  expect(items).toHaveLength(3);
  expect(items[0].textContent).toBe("one");
});

test("renders a fenced code block verbatim without inline parsing", () => {
  const { container } = renderMd("```\nconst x = **not bold**\n```");
  const code = container.querySelector("pre code");
  expect(code?.textContent).toBe("const x = **not bold**");
  expect(container.querySelector("strong")).toBeNull();
});

test("renders headings at a demoted level", () => {
  const { container } = renderMd("# Title");
  expect(container.querySelector("h3")?.textContent).toBe("Title");
});

test("only makes http links clickable", () => {
  renderMd("[safe](https://example.com) and [unsafe](javascript:alert(1))");
  const link = screen.getByText("safe");
  expect(link.tagName).toBe("A");
  expect(link).toHaveAttribute("href", "https://example.com");
  const unsafe = screen.getByText("unsafe");
  expect(unsafe.tagName).not.toBe("A");
});

test("plain text passes through as a paragraph", () => {
  const { container } = renderMd("just a line");
  expect(container.querySelector("p")?.textContent).toBe("just a line");
});
