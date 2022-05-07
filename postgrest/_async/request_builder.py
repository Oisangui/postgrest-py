from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from httpx import Headers, QueryParams
from pydantic import ValidationError

from ..base_request_builder import (
    APIResponse,
    BaseFilterRequestBuilder,
    BaseSelectRequestBuilder,
    CountMethod,
    pre_delete,
    pre_insert,
    pre_select,
    pre_update,
    pre_upsert,
)
from ..exceptions import APIError
from ..types import ReturnMethod
from ..utils import AsyncClient


class QueryRequestBuilder(ABC):
    @abstractmethod
    async def execute(self) -> APIResponse:
        """Execute the query.

        .. tip::
            This is the last method called, after the query is built.

        Returns:
            :class:`APIResponse`

        Raises:
            :class:`APIError` If the API raised an error.
        """
        raise NotImplementedError("Children class is supposed to have this method")


class AsyncQueryRequestBuilder(QueryRequestBuilder):
    def __init__(
        self,
        session: AsyncClient,
        path: str,
        http_method: str,
        headers: Headers,
        params: QueryParams,
        json: dict,
    ) -> None:
        self.session = session
        self.path = path
        self.http_method = http_method
        self.headers = headers
        self.params = params
        self.json = json

    async def execute(self) -> APIResponse:
        r = await self.session.request(
            self.http_method,
            self.path,
            json=self.json,
            params=self.params,
            headers=self.headers,
        )

        try:
            if (
                200 <= r.status_code <= 299
            ):  # Response.ok from JS (https://developer.mozilla.org/en-US/docs/Web/API/Response/ok)
                return APIResponse.from_http_request_response(r)
            else:
                raise APIError(r.json())
        except ValidationError as e:
            raise APIError(r.json()) from e


class AsyncMaybeSingleRequestBuilder(AsyncQueryRequestBuilder):
    async def execute(self) -> APIResponse:
        try:
            r = await super().execute()
        except APIError as e:
            if e.details and "Results contain 0 rows" in e.details:
                return APIResponse.from_dict(
                    {
                        "data": None,
                        "error": None,
                        "count": 0,  # NOTE: needs to take value from res.count
                    }
                )
        return r


class AsyncQueryFactory:
    def __init__(
        self,
        session: AsyncClient,
        path: str,
        http_method: str,
        headers: Headers,
        params: QueryParams,
        json: dict,
    ) -> None:
        self.session = session
        self.path = path
        self.http_method = http_method
        self.headers = headers
        self.params = params
        self.json = json

    @property
    def is_single(self):
        return self.headers.get("Accept") == "application/vnd.pgrst.object+json"

    @property
    def is_maybe_single(self):
        cond = (
            "x-maybeSingle" in self.headers
            and self.headers["x-maybeSingle"].lower() == "true"
        )
        return self.is_single and cond

    @property
    def request_builder(self) -> QueryRequestBuilder:
        if self.is_maybe_single:
            return AsyncMaybeSingleRequestBuilder(
                headers=self.headers,
                http_method=self.http_method,
                json=self.json,
                params=self.params,
                path=self.path,
                session=self.session,
            )
        else:
            return AsyncQueryRequestBuilder(
                headers=self.headers,
                http_method=self.http_method,
                json=self.json,
                params=self.params,
                path=self.path,
                session=self.session,
            )

    async def execute(self) -> APIResponse:
        return await self.request_builder.execute()


# ignoring type checking as a workaround for https://github.com/python/mypy/issues/9319
class AsyncFilterRequestBuilder(BaseFilterRequestBuilder, AsyncQueryFactory):  # type: ignore
    def __init__(
        self,
        session: AsyncClient,
        path: str,
        http_method: str,
        headers: Headers,
        params: QueryParams,
        json: dict,
    ) -> None:
        BaseFilterRequestBuilder.__init__(self, session, headers, params)
        AsyncQueryFactory.__init__(
            self, session, path, http_method, headers, params, json
        )


# ignoring type checking as a workaround for https://github.com/python/mypy/issues/9319
class AsyncSelectRequestBuilder(BaseSelectRequestBuilder, AsyncQueryFactory):  # type: ignore
    def __init__(
        self,
        session: AsyncClient,
        path: str,
        http_method: str,
        headers: Headers,
        params: QueryParams,
        json: dict,
    ) -> None:
        BaseSelectRequestBuilder.__init__(self, session, headers, params)
        AsyncQueryFactory.__init__(
            self, session, path, http_method, headers, params, json
        )


class AsyncRequestBuilder:
    def __init__(self, session: AsyncClient, path: str) -> None:
        self.session = session
        self.path = path

    def select(
        self,
        *columns: str,
        count: Optional[CountMethod] = None,
    ) -> AsyncSelectRequestBuilder:
        """Run a SELECT query.

        Args:
            *columns: The names of the columns to fetch.
            count: The method to use to get the count of rows returned.
        Returns:
            :class:`AsyncSelectRequestBuilder`
        """
        method, params, headers, json = pre_select(*columns, count=count)
        return AsyncSelectRequestBuilder(
            self.session, self.path, method, headers, params, json
        )

    def insert(
        self,
        json: dict,
        *,
        count: Optional[CountMethod] = None,
        returning: ReturnMethod = ReturnMethod.representation,
        upsert: bool = False,
    ) -> AsyncQueryFactory:
        """Run an INSERT query.

        Args:
            json: The row to be inserted.
            count: The method to use to get the count of rows returned.
            returning: Either 'minimal' or 'representation'
            upsert: Whether the query should be an upsert.
        Returns:
            :class:`AsyncQueryFactory`
        """
        method, params, headers, json = pre_insert(
            json,
            count=count,
            returning=returning,
            upsert=upsert,
        )
        return AsyncQueryFactory(self.session, self.path, method, headers, params, json)

    def upsert(
        self,
        json: dict,
        *,
        count: Optional[CountMethod] = None,
        returning: ReturnMethod = ReturnMethod.representation,
        ignore_duplicates: bool = False,
    ) -> AsyncQueryFactory:
        """Run an upsert (INSERT ... ON CONFLICT DO UPDATE) query.

        Args:
            json: The row to be inserted.
            count: The method to use to get the count of rows returned.
            returning: Either 'minimal' or 'representation'
            ignore_duplicates: Whether duplicate rows should be ignored.
        Returns:
            :class:`AsyncQueryFactory`
        """
        method, params, headers, json = pre_upsert(
            json,
            count=count,
            returning=returning,
            ignore_duplicates=ignore_duplicates,
        )
        return AsyncQueryFactory(self.session, self.path, method, headers, params, json)

    def update(
        self,
        json: dict,
        *,
        count: Optional[CountMethod] = None,
        returning: ReturnMethod = ReturnMethod.representation,
    ) -> AsyncFilterRequestBuilder:
        """Run an UPDATE query.

        Args:
            json: The updated fields.
            count: The method to use to get the count of rows returned.
            returning: Either 'minimal' or 'representation'
        Returns:
            :class:`AsyncFilterRequestBuilder`
        """
        method, params, headers, json = pre_update(
            json,
            count=count,
            returning=returning,
        )
        return AsyncFilterRequestBuilder(
            self.session, self.path, method, headers, params, json
        )

    def delete(
        self,
        *,
        count: Optional[CountMethod] = None,
        returning: ReturnMethod = ReturnMethod.representation,
    ) -> AsyncFilterRequestBuilder:
        """Run a DELETE query.

        Args:
            count: The method to use to get the count of rows returned.
            returning: Either 'minimal' or 'representation'
        Returns:
            :class:`AsyncFilterRequestBuilder`
        """
        method, params, headers, json = pre_delete(
            count=count,
            returning=returning,
        )
        return AsyncFilterRequestBuilder(
            self.session, self.path, method, headers, params, json
        )
