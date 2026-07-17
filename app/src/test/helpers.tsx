import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ApiClient } from "../lib/api/client";
import { ConnectionContext } from "../lib/connection";

export function renderWithConnection(
  ui: ReactNode,
  { api, queryClient }: { api: Partial<ApiClient>; queryClient?: QueryClient },
) {
  const client = queryClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConnectionContext.Provider
        value={{
          status: "ready",
          api: api as ApiClient,
          dataRoot: "/tmp/data",
          baseUrl: "http://127.0.0.1:8686",
          retry: () => {},
        }}
      >
        {ui}
      </ConnectionContext.Provider>
    </QueryClientProvider>,
  );
}
