import "@testing-library/jest-dom/vitest";

// 部分 jsdom 版本缺少 Blob.text()，用 FileReader 补齐
if (typeof File !== "undefined" && !File.prototype.text) {
  File.prototype.text = function text(this: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}
